"""Culture pack schema and the user's selection. No culture or script is hardcoded:
everything comes from JSON files in app/culture_packs/."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .common import Setting


class ScriptInfo(BaseModel):
    id: str
    label: str
    ranges: list[tuple[str, str]]  # unicode hex ranges, used to verify output text

    def contains(self, ch: str) -> bool:
        cp = ord(ch)
        return any(int(a, 16) <= cp <= int(b, 16) for a, b in self.ranges)


class Source(BaseModel):
    id: str  # S1
    title: str
    url: str


class CrossCheck(BaseModel):
    """An independent model's opinion of one fact. Agreement is NOT proof, but disagreement is a flag."""

    model: str
    verdict: Literal["agree", "disagree", "unsure"]
    note: str = ""


class Fact(BaseModel):
    id: str  # F010
    category: str  # region, dialect, greeting, kinship, gesture, architecture, clothing, food, ...
    text: str  # the claim, in English
    term: str = ""  # the word/phrase in its own script, if the fact is about a term
    roman: str = ""
    source_ids: list[str] = Field(default_factory=list)
    # how the claim got here: read a page | saw it in a search-result summary | model's own memory
    basis: Literal["page_read", "search_summary", "model_knowledge"]
    confidence: Literal["high", "medium", "low"]
    uncertain: bool = False  # a human or the pipeline should double-check before relying on it
    note: str = ""
    crosschecks: list[CrossCheck] = Field(default_factory=list)

    @property
    def flagged(self) -> bool:
        """Uncertain by declaration, or any cross-check disagreed / was unsure."""
        return self.uncertain or any(c.verdict != "agree" for c in self.crosschecks)


class StyleRule(BaseModel):
    id: str
    text: str
    fact_ids: list[str] = Field(default_factory=list)  # the facts this rule rests on


class IdentityMarker(BaseModel):
    """A word that asserts religion, caste or community (a surname, a title, a place of worship). Using one is not
    wrong, but the source must establish that identity, or a decision must say why and be reviewed by a person."""

    term: str
    marks: str  # what it asserts, e.g. "Sikh religious identity"


class AvoidTerm(BaseModel):
    """A word that does not belong in this culture's output (an English word spelled out in the script, a form
    from another language's register), with what to write instead."""

    term: str
    prefer: str = ""
    note: str = ""


class CulturePack(BaseModel):
    id: str
    culture: str
    language_family: str = ""
    regions: list[str]
    settings: list[Setting]
    supported_scripts: list[str]  # ids from scripts.json
    default_script: str  # suggested in the UI, still chosen by the user
    avoid_mixing_with: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    style_rules: list[StyleRule] = Field(default_factory=list)
    identity_markers: list[IdentityMarker] = Field(default_factory=list)
    avoid_terms: list[AvoidTerm] = Field(default_factory=list)
    lists_note: str = ""  # how the two lists above were built and what is unverified
    provenance: str = ""  # plain statement of how the pack was built and what is unverified

    @model_validator(mode="after")
    def _check_integrity(self):
        if len({f.id for f in self.facts}) != len(self.facts):
            raise ValueError("duplicate fact ids")
        known = {s.id for s in self.sources}
        for f in self.facts:
            missing = [s for s in f.source_ids if s not in known]
            if missing:
                raise ValueError(f"{f.id} cites unknown source(s) {missing}")
            if f.basis != "model_knowledge" and not f.source_ids:
                raise ValueError(f"{f.id} claims a source basis but cites no source")
            # honesty rule: an unsourced claim cannot be presented as certain
            if f.basis == "model_knowledge" and not f.flagged and not any(c.verdict == "agree" for c in f.crosschecks):
                raise ValueError(f"{f.id} is from model knowledge: mark it uncertain or cross-check it")
        fact_ids = {f.id for f in self.facts}
        for r in self.style_rules:
            bad = [i for i in r.fact_ids if i not in fact_ids]
            if bad:
                raise ValueError(f"style rule {r.id} cites unknown fact(s) {bad}")
        return self

    def for_prompt(self, include_flagged: bool = True) -> str:
        """The pack rendered as text for the adaptation prompts (Steps 8 and 10)."""
        lines = [f"CULTURE: {self.culture} (avoid mixing with: {', '.join(self.avoid_mixing_with) or 'n/a'})"]
        for rule in self.style_rules:
            lines.append(f"RULE {rule.id}: {rule.text}")
        by_cat: dict[str, list[Fact]] = {}
        for f in self.facts:
            if include_flagged or not f.flagged:
                by_cat.setdefault(f.category, []).append(f)
        for cat, facts in by_cat.items():
            lines.append(f"\n[{cat}]")
            for f in facts:
                term = (f" {f.term}" + (f" ({f.roman})" if f.roman else "")) if f.term else ""
                mark = " [UNCERTAIN: flag any decision that relies on this]" if f.flagged else ""
                lines.append(f"- {f.id}:{term} {f.text}{mark}")
        if self.identity_markers:
            lines.append("\n[identity markers] These assert religion, caste or community. Do NOT use one unless the source "
                         "establishes that identity; if you must, add a decision about that entity with uncertain=true saying why:")
            lines += [f"- {m.term}: {m.marks}" for m in self.identity_markers]
        if self.avoid_terms:
            lines.append("\n[avoid in the output] Do not write these; use the preferred form:")
            lines += [f"- {t.term}" + (f" -> {t.prefer}" if t.prefer else "") + (f" ({t.note})" if t.note else "") for t in self.avoid_terms]
        return "\n".join(lines)


class CultureSelection(BaseModel):
    """What the user picked. Every field is required: no baked-in defaults."""

    pack_id: str
    region: str
    setting: Setting
    output_script: str  # script id, e.g. "gurmukhi"

    def validate_against(self, pack: CulturePack, scripts: dict[str, ScriptInfo]) -> None:
        if pack.id != self.pack_id:
            raise ValueError(f"selection is for {self.pack_id}, pack is {pack.id}")
        if self.region not in pack.regions:
            raise ValueError(f"region {self.region!r} not in {pack.regions}")
        if self.setting not in pack.settings:
            raise ValueError(f"setting {self.setting.value!r} not supported by {pack.id}")
        if self.output_script not in pack.supported_scripts:
            raise ValueError(f"script {self.output_script!r} not supported by {pack.id}")
        if self.output_script not in scripts:
            raise ValueError(f"script {self.output_script!r} missing from scripts.json")
