from pathlib import Path

import pytest

from app.models import (
    Character, Costume, GateError, Project, ProjectStatus, Prop, Scene, Severity,
    SourceScene, StateChange, StateChangeKind as K,
)
from app.pipeline import check_continuity, normalize

FIXTURE = Path(__file__).parent / "fixtures" / "extracted_sample.json"
A, B, C = "CHAR_A", "CHAR_B", "CHAR_C"
LETTER = "PROP_LETTER"


def S(n, chars=(A,), start=None, end=None, events=(), time="day", costumes=None):
    """A canonical scene; start/end are {prop id: holder id} dicts."""
    return Scene(
        scene_id=f"SC{n:02d}", number=n, location_id="LOC_X", time=time, characters=list(chars),
        prop_holder_start=start or {}, prop_holder_end=end or {}, state_changes=list(events),
        costumes=costumes if costumes is not None else {c: "COST_1" for c in chars},
    )


def build(*scenes, costumes=None) -> Project:
    ids = [A, B, C]
    p = Project(status=ProjectStatus.NORMALIZED)
    p.characters = [Character(id=i, name=i[-1]) for i in ids]
    p.costumes = costumes or [Costume(id="COST_1", character_id=A, garments="blue jacket")]
    used = {pid for s in scenes for pid in (*s.prop_holder_start, *s.prop_holder_end)}
    used |= {e.item for s in scenes for e in s.state_changes if e.item.startswith("PROP_")}
    p.props = [Prop(id=pid, name=pid[5:].lower(),
                    scene_ids=[s.scene_id for s in scenes if pid in {*s.prop_holder_start, *s.prop_holder_end,
                                                                     *(e.item for e in s.state_changes)}])
               for pid in sorted(used)]
    p.scenes = list(scenes)
    return p


def codes(p):
    return sorted(w.code for w in p.warnings)


def sample() -> Project:
    p = normalize(Project.model_validate_json(FIXTURE.read_text()))
    check_continuity(p)
    return p


# ---- the real extraction: the planted traps must be found ---------------------------------
def test_planted_letter_contradiction_is_an_error_naming_every_affected_scene():
    p = sample()
    w = next(w for w in p.warnings if w.code == "PROP_HOLDER_MISMATCH")
    assert w.severity == Severity.ERROR and w.entity_id == "PROP_LETTER"
    assert w.affected_scene_ids == ["SC02", "SC03", "SC04"]  # the whole stretch, incl. the silent scene 3
    assert "Uncle Hari" in w.message and "Ravi" in w.message
    assert w in p.blocking_warnings


def test_planted_costume_change_is_flagged():
    w = next(w for w in sample().warnings if w.code == "COSTUME_CHANGE_NO_REASON")
    assert w.entity_id == "CHAR_RAVI" and w.affected_scene_ids == ["SC02", "SC03"]
    assert "blue jacket" in w.message and "red checked shirt" in w.message
    assert w.severity == Severity.WARNING  # time passed between the scenes


def test_real_findings_beyond_the_planted_ones():
    got = {(w.code, w.entity_id) for w in sample().warnings}
    assert ("PROP_NOT_SHOWN", "PROP_TRAVEL_BAG") in got and ("PROP_NOT_SHOWN", "PROP_HANDKERCHIEF") in got
    assert ("INJURY_ACTIVE", "CHAR_RAVI") in got


def test_no_false_alarm_for_the_handkerchief_handover():
    # scene 3 records "Ravi gains the handkerchief", which explains the holder change from scene 2
    assert not [w for w in sample().warnings if w.code == "PROP_HOLDER_MISMATCH" and w.entity_id == "PROP_HANDKERCHIEF"]


def test_checker_marks_project_checked_and_tags_scenes_with_warning_ids():
    p = sample()
    assert p.continuity_checked
    ids = {w.id for w in p.warnings}
    assert all(set(s.continuity_warnings) <= ids for s in p.scenes)
    letter = next(w for w in p.warnings if w.code == "PROP_HOLDER_MISMATCH")
    assert letter.id in p.scenes[2].continuity_warnings  # SC03 is affected even though it never mentions the letter


def test_derived_state_shows_injury_knowledge_and_carried_props():
    st = sample().scenes[3].states
    assert st["CHAR_RAVI"].injuries == ["cut on left palm"] and st["CHAR_RAVI"].costume_id == "COST_RAVI_02"
    assert st["CHAR_MEERA"].carrying == ["PROP_LETTER"]
    assert "job offer" in st["CHAR_MEERA"].knows[0]


def test_deterministic_and_idempotent():
    p = sample()
    first = [w.model_dump() for w in p.warnings]
    check_continuity(p)
    assert [w.model_dump() for w in p.warnings] == first


# ---- props ------------------------------------------------------------------------------
def test_consistent_handover_chain_has_no_warnings():
    p = build(S(1, (A, B), start={LETTER: A}, end={LETTER: B}), S(2, (B,), start={LETTER: B}, end={LETTER: B}))
    check_continuity(p)
    assert p.warnings == []


def test_person_to_person_mismatch_is_an_error_but_place_involved_is_a_warning():
    p = build(S(1, (A,), end={LETTER: A}), S(2, (B,), start={LETTER: B}))
    check_continuity(p)
    assert p.warnings[0].severity == Severity.ERROR
    q = build(S(1, (A,), end={LETTER: "@table"}), S(2, (B,), start={LETTER: B}))
    check_continuity(q)
    assert q.warnings[0].severity == Severity.WARNING


@pytest.mark.parametrize("event", [
    StateChange(kind=K.PROP_GAIN, character_id=B, item=LETTER),
    StateChange(kind=K.PROP_TRANSFER, character_id=A, item=LETTER, to_character_id=B),
])
def test_an_event_in_the_scene_explains_the_holder_change(event):
    p = build(S(1, (A,), end={LETTER: A}), S(2, (A, B), start={LETTER: B}, events=[event]))
    check_continuity(p)
    assert "PROP_HOLDER_MISMATCH" not in codes(p)


def test_a_transfer_FROM_the_new_holder_does_not_explain_it():
    ev = StateChange(kind=K.PROP_TRANSFER, character_id=B, item=LETTER, to_character_id=C)
    p = build(S(1, (A,), end={LETTER: A}), S(2, (B, C), start={LETTER: B}, events=[ev]))
    check_continuation = check_continuity(p)
    assert "PROP_HOLDER_MISMATCH" in [w.code for w in check_continuation]


def test_prop_not_shown_when_its_holder_is_in_the_next_scene():
    p = build(S(1, (A,), end={LETTER: A}), S(2, (A,)), S(3, (A,), start={LETTER: A}))
    check_continuity(p)
    w = next(w for w in p.warnings if w.code == "PROP_NOT_SHOWN")
    assert w.affected_scene_ids == ["SC01", "SC02"]


def test_transfer_disagreeing_with_recorded_holders_is_flagged():
    ev = StateChange(kind=K.PROP_TRANSFER, character_id=A, item=LETTER, to_character_id=B)
    p = build(S(1, (A, B, C), start={LETTER: C}, end={LETTER: C}, events=[ev]))
    check_continuity(p)
    assert {"TRANSFER_SOURCE_MISMATCH", "TRANSFER_TARGET_MISMATCH"} <= set(codes(p))


# ---- costumes ---------------------------------------------------------------------------------
TWO = [Costume(id="COST_1", character_id=A, garments="blue"), Costume(id="COST_2", character_id=A, garments="red")]


def test_costume_change_with_a_story_reason_is_fine():
    two = [TWO[0], Costume(id="COST_2", character_id=A, garments="red", change_reason="spilled tea on the blue one")]
    p = build(S(1, costumes={A: "COST_1"}), S(2, costumes={A: "COST_2"}), costumes=two)
    check_continuity(p)
    assert "COSTUME_CHANGE_NO_REASON" not in codes(p)


def test_unexplained_costume_change_is_error_when_no_time_has_passed_else_warning():
    same = build(S(1, costumes={A: "COST_1"}, time="evening"), S(2, costumes={A: "COST_2"}, time="Evening"), costumes=TWO)
    check_continuity(same)
    assert same.warnings[0].severity == Severity.ERROR
    later = build(S(1, costumes={A: "COST_1"}, time="morning"), S(2, costumes={A: "COST_2"}, time="night"), costumes=TWO)
    check_continuity(later)
    assert later.warnings[0].severity == Severity.WARNING


def test_costume_is_compared_across_scenes_the_character_skips():
    p = build(S(1, costumes={A: "COST_1"}), S(2, (B,), costumes={B: "COST_1"}), S(3, costumes={A: "COST_2"}), costumes=TWO)
    check_continuity(p)
    assert next(w for w in p.warnings if w.code == "COSTUME_CHANGE_NO_REASON").affected_scene_ids == ["SC01", "SC02", "SC03"]


# ---- injuries and knowledge ------------------------------------------------------------------
def inj(kind, item, who=A):
    return StateChange(kind=kind, character_id=who, item=item)


def test_injury_persists_in_state_across_scenes_including_after_absence():
    p = build(S(1, events=[inj(K.INJURY_GAIN, "cut hand")]), S(2, (B,)), S(3, (A,)))
    check_continuity(p)
    assert p.scenes[2].states[A].injuries == ["cut hand"]
    assert any(w.code == "INJURY_ACTIVE" and w.affected_scene_ids == ["SC01", "SC03"] for w in p.warnings)


def test_healed_injury_leaves_state_and_raises_no_active_warning():
    p = build(S(1, events=[inj(K.INJURY_GAIN, "cut hand")]), S(2, events=[inj(K.INJURY_HEAL, "cut hand")]), S(3))
    check_continuity(p)
    assert p.scenes[2].states[A].injuries == [] and "INJURY_ACTIVE" not in codes(p)


def test_healing_an_injury_that_never_happened_is_flagged():
    p = build(S(1, events=[inj(K.INJURY_HEAL, "broken arm")]))
    check_continuity(p)
    assert "INJURY_HEAL_WITHOUT_INJURY" in codes(p)


def test_knowledge_accumulates_and_persists():
    p = build(S(1, events=[inj(K.KNOWLEDGE_GAIN, "the secret")]), S(2, (B,)), S(3, (A,)))
    check_continuity(p)
    assert p.scenes[2].states[A].knows == ["the secret"] and p.scenes[1].states[B].knows == []


# ---- structure ------------------------------------------------------------------------------
def test_missing_scene_gap_and_missing_location_are_errors():
    p = build(S(1), S(3))
    p.source_scenes = [SourceScene(number=n, text="x") for n in (1, 2, 3)]
    p.scenes[0].location_id = ""
    check_continuity(p)
    assert {"SCENE_MISSING", "SCENE_GAP", "MISSING_LOCATION"} <= set(codes(p))
    assert all(w.severity == Severity.ERROR for w in p.warnings if w.code.startswith("SCENE") or w.code == "MISSING_LOCATION")


def test_requires_normalized_scenes():
    with pytest.raises(ValueError):
        check_continuity(Project())


# ---- acknowledgement and re-checking -------------------------------------------------------------
def test_acknowledgement_survives_a_recheck_and_unblocks_approval():
    p = sample()
    p.warnings[0].acknowledged = True  # the letter contradiction: user says it's intentional
    check_continuity(p)
    assert p.warnings[0].code == "PROP_HOLDER_MISMATCH" and p.warnings[0].acknowledged
    assert p.blocking_warnings == []
    p.approval.characters = p.approval.plan = p.approval.costumes = True
    p.status = ProjectStatus.PLAN_READY
    p.approve()
    assert p.status == ProjectStatus.APPROVED


def test_fixing_the_data_removes_the_warning_and_a_new_problem_is_not_pre_acknowledged():
    p = build(S(1, (A,), end={LETTER: A}), S(2, (B,), start={LETTER: B}))
    check_continuity(p)
    p.warnings[0].acknowledged = True
    p.scenes[1].prop_holder_start = {LETTER: A}  # user corrects the extraction
    check_continuity(p)
    assert p.warnings == []
    p.scenes[1].prop_holder_start = {LETTER: C}  # a different contradiction appears
    check_continuity(p)
    assert len(p.warnings) == 1 and not p.warnings[0].acknowledged


def test_normalizing_again_resets_the_checked_flag_so_approval_needs_a_fresh_check():
    p = sample()
    p = normalize(p)
    assert not p.continuity_checked
    p.approval.characters = p.approval.plan = p.approval.costumes = True
    p.status = ProjectStatus.PLAN_READY
    with pytest.raises(GateError, match="continuity"):
        p.approve()
