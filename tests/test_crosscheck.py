import json

import pytest

from app.culture_packs.crosscheck import Verdict, apply_verdicts, build_prompt, crosscheck, recompute_flags, review_checklist
from app.culture_packs.loader import load_pack
from app.llm.fake import FakeLLM
from app.models import CulturePack, Fact, Source


def small_pack() -> CulturePack:
    return CulturePack(
        id="t", culture="Test", regions=["r"], settings=["rural"], supported_scripts=["gurmukhi"],
        default_script="gurmukhi", sources=[Source(id="S1", title="A page", url="http://x")],
        facts=[
            Fact(id="F1", category="kinship", text="sourced", source_ids=["S1"], basis="search_summary", confidence="high"),
            Fact(id="F2", category="kinship", text="from memory", basis="model_knowledge", confidence="medium", uncertain=True),
        ])


def V(fid, verdict, note=""):
    return Verdict(fact_id=fid, verdict=verdict, note=note)


def test_the_real_pack_loads_and_its_memory_facts_start_flagged():
    p = load_pack("majhi_punjabi")
    assert len(p.facts) > 40 and p.sources and p.style_rules
    assert all(f.flagged for f in p.facts if f.basis == "model_knowledge" and not f.crosschecks)


def test_pack_refuses_an_unflagged_fact_from_memory():
    with pytest.raises(ValueError, match="model knowledge"):
        CulturePack(id="t", culture="T", regions=["r"], settings=["rural"], supported_scripts=["gurmukhi"],
                    default_script="gurmukhi",
                    facts=[Fact(id="F", category="x", text="t", basis="model_knowledge", confidence="high")])


def test_pack_refuses_unknown_sources_and_sourceless_source_claims_and_bad_rules():
    base = dict(id="t", culture="T", regions=["r"], settings=["rural"], supported_scripts=["gurmukhi"], default_script="gurmukhi")
    with pytest.raises(ValueError, match="unknown source"):
        CulturePack(**base, facts=[Fact(id="F", category="x", text="t", source_ids=["S9"], basis="page_read", confidence="high")])
    with pytest.raises(ValueError, match="cites no source"):
        CulturePack(**base, facts=[Fact(id="F", category="x", text="t", basis="page_read", confidence="high")])
    with pytest.raises(ValueError, match="unknown fact"):
        CulturePack(**base, style_rules=[{"id": "R", "text": "t", "fact_ids": ["F404"]}])


def test_one_model_agreeing_does_not_unflag_a_memory_fact():
    p = small_pack()
    apply_verdicts(p, "azure:gpt-5", [V("F2", "agree")])
    assert p.facts[1].uncertain and p.facts[1].flagged


def test_two_informative_models_agreeing_unflags_a_memory_fact():
    p = small_pack()
    # each model objects to F1 somewhere, so neither is a rubber stamp; both agree on F2
    apply_verdicts(p, "azure:gpt-5", [V("F1", "unsure"), V("F2", "agree")])
    apply_verdicts(p, "gemini:g", [V("F1", "unsure"), V("F2", "agree")])
    assert not p.facts[1].uncertain and not p.facts[1].flagged


def test_a_reviewer_that_agrees_with_everything_does_not_count():
    p = small_pack()
    apply_verdicts(p, "azure:gpt-5", [V("F1", "unsure"), V("F2", "agree")])   # informative
    apply_verdicts(p, "rubber:stamp", [V("F1", "agree"), V("F2", "agree")])   # agrees with all
    assert p.facts[1].uncertain  # only ONE informative agreement


def test_recompute_flags_is_idempotent_and_reversible():
    p = small_pack()
    apply_verdicts(p, "a", [V("F1", "unsure"), V("F2", "agree")])
    apply_verdicts(p, "b", [V("F1", "unsure"), V("F2", "agree")])
    assert not p.facts[1].uncertain
    p.facts[1].crosschecks = p.facts[1].crosschecks[:1]  # a verdict is removed
    recompute_flags(p)
    assert p.facts[1].uncertain


def test_any_objection_keeps_it_flagged_even_with_two_agreeing():
    p = small_pack()
    for m, v in (("a", "agree"), ("b", "agree"), ("c", "disagree")):
        apply_verdicts(p, m, [V("F2", v, "wrong region")])
    assert p.facts[1].uncertain


def test_disagreement_flags_a_sourced_fact_too():
    p = small_pack()
    assert not p.facts[0].flagged
    apply_verdicts(p, "azure:gpt-5", [V("F1", "disagree", "that is Malwai usage")])
    assert p.facts[0].flagged and p.facts[0].crosschecks[0].note == "that is Malwai usage"


def test_rerunning_a_model_replaces_its_verdict_instead_of_stacking():
    p = small_pack()
    apply_verdicts(p, "m", [V("F1", "agree")])
    apply_verdicts(p, "m", [V("F1", "unsure")])
    assert [c.verdict for c in p.facts[0].crosschecks] == ["unsure"]


def test_invented_fact_ids_are_ignored_and_missing_verdicts_record_nothing():
    p = small_pack()
    n = apply_verdicts(p, "m", [V("F404", "agree"), V("F1", "agree")])
    assert n == 1 and p.facts[1].crosschecks == []  # F2 got no verdict: not silently 'agree'


def test_crosscheck_sends_every_claim_and_records_the_reply():
    p = small_pack()
    llm = FakeLLM([json.dumps({"verdicts": [{"fact_id": "F1", "verdict": "agree"}, {"fact_id": "F2", "verdict": "unsure", "note": "not sure"}]})])
    llm.model = "fake-model"
    model, n = crosscheck(p, llm)
    assert n == 2 and model == "fake:fake-model"
    assert "F1" in llm.calls[0]["prompt"] and "F2" in llm.calls[0]["prompt"]


def test_checklist_puts_flagged_facts_first_with_tickboxes_and_provenance():
    p = small_pack()
    p.provenance = "built from a test"
    apply_verdicts(p, "azure:gpt-5", [V("F1", "disagree", "wrong region")])
    md = review_checklist(p)
    part1, part2 = md.split("## Part 2")
    assert "F1" in part1 and "F2" in part1  # both flagged
    assert "wrong region" in part1 and "☐ OK" in part1 and "built from a test" in md


def test_prompt_view_marks_flagged_facts_and_can_hide_them():
    p = small_pack()
    assert "[UNCERTAIN" in p.for_prompt() and "from memory" in p.for_prompt()
    assert "from memory" not in p.for_prompt(include_flagged=False) and "sourced" in p.for_prompt(include_flagged=False)
