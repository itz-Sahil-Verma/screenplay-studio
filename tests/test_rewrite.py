import json

import pytest

from app.llm.fake import FakeLLM
from app.models import ProjectStatus, ReviewStatus, Severity
from app.pipeline import rewrite_scene, rewrite_screenplay, screenplay_text
from app.pipeline.rewrite import describe_events, rewrite_prompt, source_dialogue, verify_rewrite, SceneRewrite
from app.culture_packs.loader import load_pack, load_scripts
from app.review import acknowledge_warning, approve, review_decision
from tests.test_plan import SCENES
from tests.test_review import get_ready_to_approve

DIALOGUE = "ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ ਜੀ"  # test data only, in Gurmukhi
ACTION = "ਰਵੀ ਚਿੱਠੀ ਦੋਹਾਂ ਹੱਥਾਂ ਨਾਲ ਦਿੰਦਾ ਹੈ"


def heading(sid: str) -> str:
    return f"ਅੰਦਰੂਨੀ. ਘਰ — {int(sid[2:])}"  # the slugline, in the output script


def approved_project():
    p = get_ready_to_approve()
    acknowledge_warning(p, next(w.id for w in p.warnings if w.severity == Severity.ERROR), note="ok")
    for what in ("characters", "costumes", "plan"):
        approve(p, what)
    assert p.status == ProjectStatus.APPROVED
    return p


def rewrite_json(p, sid, mutate=None) -> str:
    """A valid rewrite built from the scene's own dialogue and events."""
    scene = next(s for s in p.scenes if s.scene_id == sid)
    lines = [{"kind": "dialogue", "character_id": spk, "text": DIALOGUE, "gloss": f"line {i}", "source_line": i}
             for i, (spk, _) in enumerate(source_dialogue(p, scene), 1)]
    events = list(range(1, len(scene.state_changes) + 1))
    lines.append({"kind": "action", "text": ACTION, "gloss": "shows the events", "event_ids": events})
    d = {"scene_id": sid, "heading": heading(sid), "lines": lines}
    if mutate:
        mutate(d)
    return json.dumps(d, ensure_ascii=False)


def happy(p, **kw):
    return FakeLLM([rewrite_json(p, s, kw.get("mutate") if s == kw.get("only") or "only" not in kw else None) for s in SCENES])


def problems_of(p, sid, mutate):
    scene = next(s for s in p.scenes if s.scene_id == sid)
    sr = SceneRewrite.model_validate_json(rewrite_json(p, sid, mutate))
    return verify_rewrite(p, load_scripts()["gurmukhi"], scene, sr)


# ---- the source side ------------------------------------------------------------------------------------------
def test_source_dialogue_is_parsed_with_speakers_in_order():
    p = approved_project()
    got = {s.scene_id: [(spk, t[:20]) for spk, t in source_dialogue(p, s)] for s in p.scenes}
    assert [spk for spk, _ in got["SC01"]] == ["CHAR_MEERA", "CHAR_RAVI", "CHAR_MEERA", "CHAR_ANU", "CHAR_RAVI"]
    assert [spk for spk, _ in got["SC02"]] == ["CHAR_UNCLE_HARI", "CHAR_RAVI", "CHAR_UNCLE_HARI", "CHAR_RAVI", "CHAR_UNCLE_HARI"]
    assert all("INT" not in t and "THE LETTER" not in t for v in got.values() for _, t in v)  # sluglines and the title are not dialogue


def test_events_are_described_for_the_prompt():
    p = approved_project()
    assert describe_events(p, p.scenes[0]) == ["prop_transfer: Postman: letter to Ravi"]


# ---- the happy path ----------------------------------------------------------------------------------------------
def test_full_rewrite_moves_to_rewritten_and_keeps_the_trace():
    p = approved_project()
    llm = happy(p)
    rewrite_screenplay(p, llm)
    assert p.status == ProjectStatus.REWRITTEN and len(llm.calls) == 4  # one call per scene
    assert [a.source_scene_id for a in p.adapted_scenes] == SCENES
    first = p.adapted_scenes[0]
    assert first.problems == [] and first.lines[0].source_scene_id == "SC01" and first.lines[0].source_line == 1
    assert first.lines[0].character_id == "CHAR_MEERA" and first.lines[-1].event_ids == [1]


def test_rewrite_requires_an_approved_project():
    p = approved_project()
    p.status = ProjectStatus.PLAN_READY
    with pytest.raises(ValueError, match="approved"):
        rewrite_screenplay(p, FakeLLM([]))


# ---- verification: what the checks catch ---------------------------------------------------------------------------
@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d["lines"][0].update(text="Sat Sri Akal ji"), "outside Gurmukhi"),
    (lambda d: d["lines"][0].update(text="ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ ji"), "outside Gurmukhi"),
    (lambda d: d["lines"][0].update(text="ਗandum ਖੇਤ"), "mixes scripts"),
    (lambda d: d["lines"][0].update(gloss=""), "gloss is empty"),
    (lambda d: d["lines"][0].update(gloss="ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ"), "write this in English"),
    (lambda d: d["lines"][0].update(character_id="CHAR_UNCLE_HARI"), "not in this scene"),
    (lambda d: d["lines"][0].update(character_id="CHAR_RAVI"), "is spoken by CHAR_MEERA"),
    (lambda d: d["lines"][0].update(character_id=""), "needs a character_id"),
    (lambda d: d["lines"][0].update(source_line=99), "not one of the"),
    (lambda d: d["lines"][1].update(decision_ids=["DEC999"]), "do not exist"),
    (lambda d: d["lines"][-1].update(event_ids=[7]), "event numbers that do not exist"),
    (lambda d: d.update(heading=" "), "heading: empty"),
    (lambda d: d.update(heading="INT. HOME - 1"), "heading: 'INT. HOME - 1' contains letters outside Gurmukhi"),
    (lambda d: d["lines"][0].update(text="ਸਤਿ ਿੰਕ ਦਾ ਠੱਪਾ"), "malformed word"),
    (lambda d: d["lines"][0].update(note="ਇਹ ਸ਼ਬਦ ਪੱਕਾ ਨਹੀਂ"), "note: write this in English"),
    (lambda d: d["lines"][0].update(source_line=0), "cites no decision"),
    (lambda d: d.update(scene_id="SC09"), "expected 'SC01'"),
])
def test_line_level_problems_are_detected(mutate, expect):
    p = approved_project()
    assert any(expect in m for m in problems_of(p, "SC01", mutate))


def test_a_lost_source_line_is_detected():
    p = approved_project()
    assert any("[3] were not adapted" in m for m in problems_of(p, "SC01", lambda d: d["lines"].pop(2)))


def test_reordered_dialogue_is_detected():
    def swap(d):
        d["lines"][0]["source_line"], d["lines"][1]["source_line"] = 2, 1
        d["lines"][0]["character_id"], d["lines"][1]["character_id"] = "CHAR_RAVI", "CHAR_MEERA"
    assert any("do not reorder" in m for m in problems_of(approved_project(), "SC01", swap))


def test_a_source_event_that_is_never_shown_is_detected():
    assert any("event(s) [1] are not shown" in m for m in problems_of(approved_project(), "SC01", lambda d: d["lines"][-1].update(event_ids=[])))


def test_splitting_one_source_line_into_two_adapted_lines_is_allowed():
    def split(d):
        d["lines"].insert(1, {**d["lines"][0], "text": "ਹਾਂ ਜੀ", "gloss": "second half of the same line"})
    assert problems_of(approved_project(), "SC01", split) == []


def test_a_valid_rewrite_has_no_problems():
    assert problems_of(approved_project(), "SC01", None) == []


# ---- the retry loop, failure isolation, regeneration -----------------------------------------------------------------
def test_a_bad_rewrite_is_retried_with_the_problems_fed_back_then_accepted():
    p = approved_project()
    bad = rewrite_json(p, "SC01", lambda d: d["lines"][0].update(text="Sat Sri Akal"))
    llm = FakeLLM([bad, rewrite_json(p, "SC01")])
    rewrite_scene(p, "SC01", llm)
    assert "outside Gurmukhi" in llm.calls[1]["prompt"]
    assert p.adapted_scenes[0].problems == [] and p.adapted_scenes[0].lines[0].text == DIALOGUE


def test_unresolved_problems_are_kept_and_flagged_not_hidden():
    p = approved_project()
    bad = rewrite_json(p, "SC01", lambda d: d["lines"][0].update(text="Sat Sri Akal"))
    rewrite_scene(p, "SC01", FakeLLM([bad] * 3))
    a = p.adapted_scenes[0]
    assert a.lines and any("outside Gurmukhi" in m for m in a.problems)


def test_one_failing_scene_does_not_lose_the_others_and_only_it_is_redone():
    p = approved_project()
    llm = FakeLLM([rewrite_json(p, "SC01"), RuntimeError("boom"), rewrite_json(p, "SC03"), rewrite_json(p, "SC04")])
    rewrite_screenplay(p, llm)
    assert p.status == ProjectStatus.APPROVED and "SC02" in p.rewrite_failed
    assert [a.source_scene_id for a in p.adapted_scenes] == ["SC01", "SC03", "SC04"]
    retry = FakeLLM([rewrite_json(p, "SC02")])
    rewrite_screenplay(p, retry)
    assert len(retry.calls) == 1 and p.status == ProjectStatus.REWRITTEN and p.rewrite_failed == {}


def test_regenerating_a_scene_bypasses_the_cache():
    p = approved_project()
    rewrite_screenplay(p, happy(p))
    fresh = FakeLLM([rewrite_json(p, "SC02", lambda d: d["lines"][0].update(gloss="second take"))])
    rewrite_scene(p, "SC02", fresh, fresh=True)
    assert len(fresh.calls) == 1 and p.adapted_scenes[1].lines[0].gloss == "second take"


def test_an_edit_the_rewrite_does_not_depend_on_regenerates_nothing():
    p = approved_project()
    rewrite_screenplay(p, happy(p))
    from app.review import edit_character, keep_scene_plan
    edit_character(p, "CHAR_ANU", role="younger daughter")  # source-side field: not in the rewrite prompt
    for sid in list(p.plan.stale_scenes):
        keep_scene_plan(p, sid)
    for d in p.decisions:
        if d.status.value == "proposed":
            review_decision(p, d.id, "accepted")
    for what in ("characters", "costumes", "plan"):
        approve(p, what)
    llm = FakeLLM([])  # any model call would fail the test
    rewrite_screenplay(p, llm)
    assert llm.calls == [] and p.status == ProjectStatus.REWRITTEN


def test_re_approval_clears_the_rewrite_and_unchanged_scenes_come_back_free():
    p = approved_project()
    rewrite_screenplay(p, happy(p))
    from app.review import edit_plan_entity, keep_scene_plan
    # the rewrite reads the ADAPTED name, so this changes the prompts of Anu's scenes only (SC01, SC03, SC04)
    edit_plan_entity(p, "character", "CHAR_ANU", name_roman="Simran", name_native="ਸਿਮਰਨ")
    for sid in list(p.plan.stale_scenes):
        keep_scene_plan(p, sid)
    for d in p.decisions:
        if d.status.value == "proposed":
            review_decision(p, d.id, "accepted")
    for what in ("characters", "costumes", "plan"):
        approve(p, what)
    assert p.status == ProjectStatus.APPROVED and p.adapted_scenes == []  # the old rewrite described an older plan
    llm = FakeLLM([rewrite_json(p, s) for s in ("SC01", "SC03", "SC04")])
    rewrite_screenplay(p, llm)
    assert len(llm.calls) == 3 and p.status == ProjectStatus.REWRITTEN  # SC02 was not affected: served from the cache


# ---- prompt contents and isolation ---------------------------------------------------------------------------------------
def test_prompt_has_accepted_decisions_but_not_rejected_ones_and_numbers_the_source():
    p = approved_project()
    scene = p.scenes[0]
    target = next(d for d in p.decisions if "SC01" in d.source_scene_ids)
    prompt = rewrite_prompt(p, load_pack("majhi_punjabi"), load_scripts(), scene)
    assert target.id in prompt and "1. [Meera / CHAR_MEERA]" in prompt and "1. prop_transfer" in prompt
    assert "dry winter, present day" in prompt  # the shared world
    target.status = ReviewStatus.REJECTED
    assert f'"id": "{target.id}"' not in rewrite_prompt(p, load_pack("majhi_punjabi"), load_scripts(), scene)


def test_system_prompt_names_no_culture():
    from app.pipeline.rewrite import SYSTEM
    assert "Majhi" not in SYSTEM and "Punjabi" not in SYSTEM and "Gurmukhi" not in SYSTEM


# ---- the readable output --------------------------------------------------------------------------------------------------------
def test_screenplay_text_renders_headings_cues_dialogue_and_optionally_the_gloss():
    p = approved_project()
    rewrite_screenplay(p, happy(p))
    text = screenplay_text(p)
    assert heading("SC01") in text and DIALOGUE in text and ACTION in text and "line 1" not in text
    assert "[line 1]" in screenplay_text(p, with_gloss=True)
    assert text.index(heading("SC01")) < text.index(heading("SC02")) < text.index(heading("SC04"))


def test_dialogue_added_because_a_decision_calls_for_it_is_allowed_if_it_cites_that_decision():
    p = approved_project()
    dec_id = p.decisions[0].id

    def add_greeting(d):
        d["lines"].insert(0, {"kind": "dialogue", "character_id": "CHAR_MEERA", "text": DIALOGUE, "gloss": "a greeting the decision adds",
                              "source_line": 0, "decision_ids": [dec_id]})
    assert problems_of(p, "SC01", add_greeting) == []


def test_a_vowel_sign_on_its_own_is_flagged_but_normal_gurmukhi_is_not():
    from app.pipeline.plan import _malformed_words
    assert _malformed_words("ਨੀਲੇ ਿੰਕ ਦਾ") == ["ਿੰਕ"]
    assert _malformed_words("ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ ਜੀ, ਮਾਂ ਜੀ। ਕਿੱਥੇ ਏਂ?") == []
    assert _malformed_words("ਵਿਹੜਾ ਚੁੱਲ੍ਹਾ ਪੁੱਤ ਦੁਪੱਟਾ ਫੁਲਕਾਰੀ") == []


# ---- cue -> character resolution (found by the eval on a spec-sized script) ------------------------------------
def _cast(*names):
    from app.models import Character, Project
    p = Project()
    p.characters = [Character(id=f"CHAR_{i}", name=n) for i, n in enumerate(names)]
    return p


def test_a_short_cue_resolves_to_the_character_introduced_with_a_title():
    from app.pipeline.rewrite import speaker_lookup
    lk = speaker_lookup(_cast("Mr. Desai", "Samir"))
    assert lk["desai"] == "CHAR_0" and lk["samir"] == "CHAR_1" and lk["mr desai"] == "CHAR_0"


def test_an_ambiguous_word_is_never_guessed():
    from app.pipeline.rewrite import speaker_lookup
    lk = speaker_lookup(_cast("Gurdev Singh", "Harjit Singh"))
    assert "singh" not in lk and lk["gurdev"] == "CHAR_0" and lk["harjit"] == "CHAR_1"


def test_titles_alone_never_identify_anyone():
    from app.pipeline.rewrite import speaker_lookup
    lk = speaker_lookup(_cast("Uncle Hari", "Uncle Ram"))
    assert "uncle" not in lk and lk["hari"] == "CHAR_0" and lk["ram"] == "CHAR_1"


def test_dialogue_by_a_short_cue_gets_its_speaker_so_the_speaker_check_applies():
    from app.models import Scene
    p = _cast("Mr. Desai", "Samir")
    scene = Scene(scene_id="SC01", number=1, source_text="INT. OFFICE - DAY\n\nDESAI\nSign here.\n\nSAMIR\nNo.\n")
    from app.pipeline.rewrite import source_dialogue
    assert source_dialogue(p, scene) == [("CHAR_0", "Sign here."), ("CHAR_1", "No.")]
