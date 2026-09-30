"""Project: the single state object for one adaptation run, with its gates.

Everything a run knows lives here and is saved as one JSON file under
workspace/<project_id>/. The status machine and the gate methods are what stop
images from being generated before the user approves.
"""
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .adaptation import AdaptedScene, AdaptationDecision
from .assets import Asset
from .bible import Character, Costume, Location, Prop
from .culture import CultureSelection
from .extraction import SourceScene
from .plan import AdaptationPlan
from .common import AssetStatus, ProjectStatus, Severity
from .scene import ContinuityWarning, Scene

S = ProjectStatus

# Forward transitions only. Going backwards is done through reopen().
ALLOWED: dict[ProjectStatus, set[ProjectStatus]] = {
    S.CREATED: {S.EXTRACTED},
    S.EXTRACTED: {S.NORMALIZED},
    S.NORMALIZED: {S.PLAN_READY},
    S.PLAN_READY: {S.APPROVED},
    S.APPROVED: {S.REWRITTEN},
    S.REWRITTEN: {S.GENERATED},
    S.GENERATED: {S.EXPORTED},
    S.EXPORTED: set(),
}


class InvalidTransition(Exception):
    pass


class GateError(Exception):
    """Raised when an action is attempted before its approval gate is open."""


class Approval(BaseModel):
    characters: bool = False
    plan: bool = False
    costumes: bool = False

    @property
    def complete(self) -> bool:
        return self.characters and self.plan and self.costumes


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=_now)
    status: ProjectStatus = ProjectStatus.CREATED

    # source
    source_filename: str = ""
    source_text: str = ""
    extraction_problems: list[str] = Field(default_factory=list)

    # per-scene source text + raw LLM extraction (input to normalization)
    source_scenes: list[SourceScene] = Field(default_factory=list)

    # user choice: one project = one culture, so nothing can leak between cultures
    selection: CultureSelection | None = None

    # canonical registry
    scenes: list[Scene] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    props: list[Prop] = Field(default_factory=list)
    costumes: list[Costume] = Field(default_factory=list)

    # every manual change (merge, rename, edit): normalization would silently undo them, so it refuses
    user_edits: list[str] = Field(default_factory=list)

    # what normalization did: merges made, merges rejected, assumptions (for the review screen)
    normalization_log: list[str] = Field(default_factory=list)

    # checks, plan, output
    warnings: list[ContinuityWarning] = Field(default_factory=list)
    continuity_checked: bool = False  # approval is impossible until the checker has run on the current records
    plan: AdaptationPlan | None = None
    decisions: list[AdaptationDecision] = Field(default_factory=list)  # the plan, flattened for review
    adapted_scenes: list[AdaptedScene] = Field(default_factory=list)
    rewrite_failed: dict[str, str] = Field(default_factory=dict)  # scene id -> error; retry just that scene
    assets: list[Asset] = Field(default_factory=list)
    approval: Approval = Field(default_factory=Approval)

    @property
    def all_problems(self) -> list[str]:
        """Everything the reviewer should look at, rebuilt from current state (never stale)."""
        out = list(self.extraction_problems)
        for sc in self.source_scenes:
            if sc.error:
                out.append(f"scene {sc.number}: extraction failed: {sc.error}")
            out.extend(f"scene {sc.number}: {m}" for m in sc.problems)
        return out

    # ---- lookups -------------------------------------------------------
    def character(self, char_id: str) -> Character | None:
        return next((c for c in self.characters if c.id == char_id), None)

    def scene(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.scene_id == scene_id), None)

    def asset(self, asset_id: str) -> Asset | None:
        return next((a for a in self.assets if a.id == asset_id), None)

    # ---- state machine -------------------------------------------------
    def transition(self, to: ProjectStatus) -> None:
        if to not in ALLOWED[self.status]:
            raise InvalidTransition(f"cannot go from {self.status.value} to {to.value}")
        self.status = to

    @property
    def blocking_warnings(self) -> list[ContinuityWarning]:
        return [
            w for w in self.warnings if w.severity == Severity.ERROR and not w.acknowledged
        ]

    def approve(self) -> None:
        """Open the gate: needs all three approvals and no unresolved errors."""
        if self.status != S.PLAN_READY:
            raise GateError(f"can only approve from plan_ready, not {self.status.value}")
        if not self.approval.complete:
            raise GateError("characters, plan and costumes must all be approved")
        if not self.continuity_checked:
            raise GateError("the continuity check has not been run on the current records")
        if self.blocking_warnings:
            ids = ", ".join(w.code for w in self.blocking_warnings)
            raise GateError(f"unresolved continuity errors: {ids}")
        self.transition(S.APPROVED)

    def assert_can_generate_images(self) -> None:
        """Called by every image endpoint. No approval, no images."""
        if self.status not in (S.APPROVED, S.REWRITTEN, S.GENERATED, S.EXPORTED):
            raise GateError(f"images blocked: project is {self.status.value}")
        if not self.approval.complete or not self.continuity_checked or self.blocking_warnings:
            raise GateError("images blocked: approval incomplete, continuity unchecked, or errors unresolved")

    def reopen(self) -> None:
        """Any edit after approval closes the gate again and marks images stale."""
        if self.status in (S.APPROVED, S.REWRITTEN, S.GENERATED, S.EXPORTED):
            self.status = S.PLAN_READY
        self.approval = Approval()
        for a in self.assets:
            if a.status == AssetStatus.GENERATED:
                a.status = AssetStatus.STALE
