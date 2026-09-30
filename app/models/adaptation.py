"""Cultural adaptation: the user's selection, the plan, and the rewritten screenplay."""
from typing import Literal

from pydantic import BaseModel, Field

from .common import Dimension, LineKind, ReviewStatus


class AdaptationDecision(BaseModel):
    """One explained cultural choice. The plan is a list of these."""

    id: str  # DEC001
    dimension: Dimension
    source_scene_ids: list[str] = Field(default_factory=list)
    entity_id: str | None = None  # CHAR_/LOC_/PROP_ this decision changes
    original: str
    adapted: str
    reason: str
    basis: Literal["pack", "judgment"] = "judgment"  # backed by pack facts, or the model's own choice
    fact_ids: list[str] = Field(default_factory=list)  # pack facts this decision relies on
    uncertain: bool = False  # model is not sure, OR it relies on a flagged fact
    uncertain_reason: str = ""  # why it is flagged (code-owned)
    status: ReviewStatus = ReviewStatus.PROPOSED
    reviewer_note: str = ""


class AdaptedLine(BaseModel):
    source_scene_id: str  # traceability back to the source scene
    decision_ids: list[str] = Field(default_factory=list)  # ...and to the plan
    character_id: str | None = None
    kind: LineKind = LineKind.DIALOGUE
    text: str  # in the output script
    gloss: str = ""  # English gloss so reviewers who don't read the script can check
    source_line: int | None = None  # which numbered source dialogue line this adapts (dialogue only)
    event_ids: list[int] = Field(default_factory=list)  # which numbered source events it depicts
    uncertain: bool = False  # the model is unsure of word choice, spelling or dialect
    note: str = ""


class AdaptedScene(BaseModel):
    source_scene_id: str
    heading: str = ""
    lines: list[AdaptedLine] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)  # unresolved verification problems, for the reviewer
