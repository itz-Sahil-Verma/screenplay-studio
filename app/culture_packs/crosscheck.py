"""Cross-check a culture pack with independent models, and produce a human review checklist.

Run:  python -m app.culture_packs.crosscheck majhi_punjabi azure gemini

Models share training data with whoever drafted the pack, so their agreement is NOT proof.
What it does give: disagreement is a cheap red flag. Rules applied here:
  * any 'disagree' or 'unsure' flags the fact (Fact.flagged), sourced or not;
  * a fact from model memory is un-flagged only if at least two INFORMATIVE models agree and none objects.
    A model is informative only if it objected to at least one claim somewhere in the pack: a reviewer
    that agrees with everything is rubber-stamping and tells us nothing.
Nothing here can mark a fact as verified by a human. That is a separate, manual step.
"""
import json
import logging
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.llm.base import LLMClient, generate_structured
from app.models import CrossCheck, CulturePack

from .loader import BASE, load_pack

log = logging.getLogger(__name__)


class Verdict(BaseModel):
    fact_id: str
    verdict: Literal["agree", "disagree", "unsure"]
    note: str = ""


class Verdicts(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


SYSTEM = """You are a reviewer checking claims about a regional culture and dialect for a screenwriting tool.
For each claim, judge whether it is accurate for the culture named. If a Gurmukhi/native-script term is given,
also check its spelling and meaning.

Rules:
- Answer "agree" only if you are confident the claim is accurate for THIS culture and region.
- Answer "disagree" if it is wrong, or is true of a different region/dialect but not this one.
- Answer "unsure" if you do not know. Do not guess to be agreeable.
- Keep each note under 25 words; explain any disagree/unsure.
- Return one verdict for EVERY fact_id given. Output JSON for the given schema only."""


def build_prompt(pack: CulturePack) -> str:
    lines = [f"Culture: {pack.culture}. Region: {', '.join(pack.regions)} (India).", "", "CLAIMS:"]
    for f in pack.facts:
        term = f" | term: {f.term}" + (f" ({f.roman})" if f.roman else "") if f.term else ""
        lines.append(f"- {f.id} [{f.category}] {f.text}{term}")
    return "\n".join(lines)


def label(client: LLMClient) -> str:
    return f"{client.name}:{getattr(client, 'deployment', None) or getattr(client, 'model', '')}"


def apply_verdicts(pack: CulturePack, model: str, verdicts: list[Verdict]) -> int:
    """Record one model's verdicts (replacing its earlier ones), then recompute uncertainty."""
    by_id = {f.id: f for f in pack.facts}
    n = 0
    for v in verdicts:
        f = by_id.get(v.fact_id)
        if f is None:
            continue  # the model invented an id: ignore it
        f.crosschecks = [c for c in f.crosschecks if c.model != model]
        f.crosschecks.append(CrossCheck(model=model, verdict=v.verdict, note=v.note.strip()))
        n += 1
    recompute_flags(pack)
    return n


def recompute_flags(pack: CulturePack) -> None:
    """Re-derive `uncertain` for memory-only facts from the recorded verdicts. Idempotent."""
    informative = {c.model for f in pack.facts for c in f.crosschecks if c.verdict != "agree"}
    for f in pack.facts:
        if f.basis == "model_knowledge":
            agree = {c.model for c in f.crosschecks if c.verdict == "agree"} & informative
            objections = [c for c in f.crosschecks if c.verdict != "agree"]
            f.uncertain = not (len(agree) >= 2 and not objections)


def crosscheck(pack: CulturePack, client: LLMClient) -> tuple[str, int]:
    """One model call for the whole pack. Returns (model label, verdicts recorded)."""
    result = generate_structured(client, SYSTEM, build_prompt(pack), Verdicts)
    model = label(client)
    return model, apply_verdicts(pack, model, result.verdicts)


def save_pack(pack: CulturePack, pack_id: str) -> Path:
    path = BASE / "packs" / f"{pack_id}.json"
    path.write_text(json.dumps(pack.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def review_checklist(pack: CulturePack) -> str:
    """One page for a human who speaks the language. Flagged facts come first."""
    src = {s.id: s for s in pack.sources}

    def row(f) -> str:
        checks = "; ".join(f"{c.model.split(':')[0]}: {c.verdict}" + (f" ({c.note})" if c.note and c.verdict != "agree" else "")
                           for c in f.crosschecks) or "not cross-checked"
        term = f"{f.term} ({f.roman})" if f.term else ""
        basis = {"page_read": "read in a page", "search_summary": "search summary", "model_knowledge": "AI memory, no source"}[f.basis]
        cites = ", ".join(src[s].title for s in f.source_ids) or "none"
        return (f"| {f.id} | {f.text} | {term} | {basis} ({f.confidence}) | {checks} | {cites} | ☐ OK  ☐ Wrong  ☐ Not sure |")

    head = "| ID | Claim | Term | Where it came from | AI cross-check | Source | Your verdict |\n|---|---|---|---|---|---|---|"
    flagged = [f for f in pack.facts if f.flagged]
    rest = [f for f in pack.facts if not f.flagged]
    return "\n".join([
        f"# Review checklist: {pack.culture}",
        "",
        "Thank you for helping. You do not need to check everything: start with Part 1.",
        "For each row tick OK if it matches how people actually speak and live in the Majha area "
        "(Amritsar, Gurdaspur, Tarn Taran, Pathankot), Wrong if not (write the correction next to it), "
        "or Not sure. Please check the spelling of any Gurmukhi term.",
        "",
        f"## Part 1: please check these first ({len(flagged)} flagged as uncertain)", "", head,
        *(row(f) for f in flagged), "",
        f"## Part 2: the rest, if you have time ({len(rest)})", "", head,
        *(row(f) for f in rest), "",
        "## How this pack was built", "", pack.provenance, "",
    ])


def make_client(provider: str) -> LLMClient:
    """Build a specific provider, regardless of LLM_PROVIDER. Cross-checking is the one place we want
    several providers on purpose."""
    if provider == "azure":
        from app.llm.azure import AzureOpenAIClient
        return AzureOpenAIClient(settings.azure_deployment_adapt)
    if provider == "gemini":
        from app.llm.gemini import GeminiClient
        return GeminiClient(settings.gemini_model_adapt)
    if provider == "groq":
        from app.llm.groq_client import GroqClient
        return GroqClient(settings.groq_model_adapt)
    raise ValueError(f"unknown provider {provider!r}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m app.culture_packs.crosscheck <pack_id> <provider> [<provider> ...]")
        return 2
    pack_id, providers = argv[0], argv[1:]
    pack = load_pack(pack_id)
    ok = 0
    for prov in providers:
        try:
            model, n = crosscheck(pack, make_client(prov))
            print(f"{model}: {n}/{len(pack.facts)} verdicts recorded")
            ok += 1
        except Exception as e:  # noqa: BLE001: one failing provider must not lose the others' work
            print(f"{prov}: FAILED ({type(e).__name__}: {str(e)[:200]})")
    if ok:
        save_pack(pack, pack_id)
        out = BASE / "reviews" / f"{pack_id}_review.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(review_checklist(pack), encoding="utf-8")
        print(f"saved pack and checklist -> {out.relative_to(BASE.parent.parent)}")
    return 0 if ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    sys.exit(main(sys.argv[1:]))
