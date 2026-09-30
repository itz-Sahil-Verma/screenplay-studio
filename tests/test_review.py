import pytest

from app.llm.fake import FakeLLM
from app.models import GateError, ProjectStatus, ReviewStatus, Severity, AssetKind, AssetStatus, Asset
from app.pipeline import build_plan, normalize
from app.review import (ReviewError, acknowledge_warning, apply_plan_to_records, approve, blockers, edit_character,
                        edit_plan_entity, keep_scene_plan, merge, review_decision, try_finalize, unapprove)
from tests.test_plan import SCENES, dec, entity_json, happy, ready_project, scene_json


def planned(**kw):
    p = ready_project()
    build_plan(p, happy(p, **kw))
    return p


def review_all(p, status="accepted"):
    for d in p.decisions:
        review_decision(p, d.id, status)


def get_ready_to_approve():
    """A plan with the costume change explained and every decision accepted."""
    p = planned(decisions=[dec("CHAR_RAVI", dim="verbal")])
    edit_plan_entity(p, "costume", "COST_RAVI_02", change_reason="changes for the evening after washing up")
    for sid in list(p.plan.stale_scenes):  # the reviewer looks at the affected scenes and keeps their plans
        keep_scene_plan(p, sid)
    review_all(p)
    return p


# ---- edits reopen the gate and report what they affect -----------------------------------------------------
def test_editing_a_character_returns_affected_scenes_logs_it_and_reopens():
    p = planned()
    p.approval.characters = True
    affected = edit_character(p, "CHAR_ANU", role="the younger daughter")
    assert affected == ["SC01", "SC03", "SC04"]  # only Anu's scenes
    assert p.approval.characters is False and p.user_edits
    assert set(SCENES[0:1]) <= set(p.plan.stale_scenes) and "SC02" not in p.plan.stale_scenes


def test_edit_validation():
    p = planned()
    with pytest.raises(ReviewError, match="cannot edit"):
        edit_character(p, "CHAR_ANU", id="X")
    with pytest.raises(ReviewError, match="unknown character"):
        edit_character(p, "CHAR_NOPE", name="x")
    with pytest.raises(ReviewError, match="empty"):
        edit_character(p, "CHAR_ANU", name="  ")


def test_an_edit_after_approval_steps_back_and_stales_generated_images():
    p = get_ready_to_approve()
    for w in p.warnings:
        if w.severity == Severity.ERROR:
            acknowledge_warning(p, w.id, note="intentional")
    for what in ("characters", "costumes", "plan"):
        approve(p, what)
    assert p.status == ProjectStatus.APPROVED
    p.assets.append(Asset(id="A1", kind=AssetKind.CHARACTER_REF, entity_id="CHAR_RAVI", status=AssetStatus.GENERATED))
    edit_character(p, "CHAR_RAVI", personality="quiet")
    assert p.status == ProjectStatus.PLAN_READY and not p.approval.complete
    assert p.assets[0].status == AssetStatus.STALE


def test_normalizing_again_refuses_to_discard_manual_edits_unless_forced():
    p = planned()
    edit_character(p, "CHAR_ANU", role="x")
    p.status = ProjectStatus.NORMALIZED
    with pytest.raises(ValueError, match="manual edit"):
        normalize(p)
    normalize(p, force=True)
    assert p.user_edits == [] and next(c for c in p.characters if c.id == "CHAR_ANU").role != "x"


# ---- merges ------------------------------------------------------------------------------------------------------
def test_merging_characters_moves_every_reference():
    p = planned(decisions=[dec("CHAR_POSTMAN", adapted="postman thing")])
    affected = merge(p, "character", "CHAR_UNCLE_HARI", "CHAR_POSTMAN")
    assert affected == ["SC01", "SC02"]
    hari = next(c for c in p.characters if c.id == "CHAR_UNCLE_HARI")
    assert "Postman" in hari.aliases and hari.scene_ids == ["SC01", "SC02"]
    assert not any(c.id == "CHAR_POSTMAN" for c in p.characters)
    sc1 = p.scenes[0]
    assert "CHAR_POSTMAN" not in sc1.characters and "CHAR_UNCLE_HARI" in sc1.characters
    assert "CHAR_POSTMAN" not in sc1.costumes and sc1.costumes["CHAR_UNCLE_HARI"] == "COST_POSTMAN_01"
    assert all(c.character_id != "CHAR_POSTMAN" for c in p.costumes)
    assert all("CHAR_POSTMAN" not in (e.character_id, e.to_character_id) for s in p.scenes for e in s.state_changes)
    assert not any(e.character_id == "CHAR_POSTMAN" for e in p.plan.entities.characters)
    assert all(d.entity_id != "CHAR_POSTMAN" for d in p.decisions)  # decisions follow the merge
    assert "CHAR_POSTMAN" not in " ".join(p.plan.problems)  # the plan is still consistent


def test_people_who_share_a_scene_cannot_be_merged():
    p = planned()
    with pytest.raises(ReviewError, match="appear together"):
        merge(p, "character", "CHAR_RAVI", "CHAR_MEERA")
    assert any(c.id == "CHAR_MEERA" for c in p.characters)  # nothing changed


def test_merge_validation():
    p = planned()
    with pytest.raises(ReviewError, match="itself"):
        merge(p, "prop", "PROP_CUP", "PROP_CUP")
    with pytest.raises(ReviewError, match="unknown kind"):
        merge(p, "spaceship", "a", "b")
    with pytest.raises(ReviewError, match="unknown prop"):
        merge(p, "prop", "PROP_CUP", "PROP_NOPE")
    with pytest.raises(ReviewError, match="different characters"):
        merge(p, "costume", "COST_RAVI_01", "COST_MEERA_01")


def test_merging_props_and_locations_and_costumes():
    p = planned()
    merge(p, "prop", "PROP_CUP", "PROP_TEA")
    assert not any(x.id == "PROP_TEA" for x in p.props)
    assert "tea" in next(x for x in p.props if x.id == "PROP_CUP").aliases
    assert "PROP_TEA" not in p.scenes[2].prop_holder_start
    merge(p, "location", "LOC_FAMILY_HOME", "LOC_DUSTY_ROAD_OUTSIDE_THE_VILLAGE")
    assert {s.location_id for s in p.scenes} == {"LOC_FAMILY_HOME"}


def test_merging_ravis_two_costumes_removes_the_unexplained_change_warning():
    p = planned()
    assert any(w.code == "COSTUME_CHANGE_NO_REASON" for w in p.warnings)
    merge(p, "costume", "COST_RAVI_01", "COST_RAVI_02")
    assert not any(w.code == "COSTUME_CHANGE_NO_REASON" for w in p.warnings)
    assert p.scenes[2].costumes["CHAR_RAVI"] == "COST_RAVI_01"


# ---- editing the plan ---------------------------------------------------------------------------------------------
def test_renaming_in_the_plan_marks_only_that_characters_scenes_stale():
    p = planned()
    affected = edit_plan_entity(p, "character", "CHAR_ANU", name_roman="Simran", name_native="ਸਿਮਰਨ")
    assert affected == ["SC01", "SC03", "SC04"]
    assert sorted(p.plan.stale_scenes) == ["SC01", "SC03", "SC04"]
    assert next(c for c in p.plan.entities.characters if c.character_id == "CHAR_ANU").name_roman == "Simran"


def test_plan_edits_are_verified_and_validated():
    p = planned()
    edit_plan_entity(p, "character", "CHAR_ANU", name_native="Anu")  # Latin in a Gurmukhi field
    assert any("outside Gurmukhi" in m for m in p.plan.problems)
    with pytest.raises(ReviewError, match="cannot edit"):
        edit_plan_entity(p, "character", "CHAR_ANU", character_id="CHAR_X")
    with pytest.raises(ReviewError, match="no character"):
        edit_plan_entity(p, "character", "CHAR_NOPE", name_roman="x")
    with pytest.raises(ReviewError, match="unknown kind"):
        edit_plan_entity(p, "planet", "x")


def test_a_replanned_scene_is_no_longer_stale():
    from app.pipeline import replan_scene
    p = planned()
    edit_plan_entity(p, "character", "CHAR_ANU", name_roman="Simran", name_native="ਸਿਮਰਨ")
    replan_scene(p, "SC01", FakeLLM([scene_json("SC01")]))
    assert "SC01" not in p.plan.stale_scenes and "SC03" in p.plan.stale_scenes


# ---- decisions ------------------------------------------------------------------------------------------------------
def test_accepting_rejecting_and_editing_decisions():
    p = planned(decisions=[dec(adapted="a"), dec(adapted="b", original="o2")])
    review_decision(p, "DEC001", "accepted", note="ok")
    review_decision(p, "DEC002", "rejected")
    assert (p.decisions[0].status, p.decisions[0].reviewer_note) == (ReviewStatus.ACCEPTED, "ok")
    assert p.decisions[1].status == ReviewStatus.REJECTED
    review_decision(p, "DEC001", "proposed", adapted="a better version")
    assert p.decisions[0].status == ReviewStatus.EDITED and p.decisions[0].adapted == "a better version"
    assert p.plan.entities.decisions[0].adapted == "a better version"  # written into the plan itself
    assert p.decisions[1].status == ReviewStatus.REJECTED  # the others kept their review


def test_an_edited_decision_survives_a_plan_refresh():
    from app.review import _refresh_plan
    p = planned(decisions=[dec(adapted="a")])
    review_decision(p, "DEC001", "accepted", adapted="mine")
    _refresh_plan(p)
    assert p.decisions[0].adapted == "mine"


def test_decision_review_validation_and_narrow_approval_reset():
    p = planned(decisions=[dec()])
    p.approval.characters = p.approval.plan = True
    with pytest.raises(ReviewError, match="status must be"):
        review_decision(p, "DEC001", "maybe")
    with pytest.raises(ReviewError, match="unknown decision"):
        review_decision(p, "DEC999", "accepted")
    with pytest.raises(ReviewError, match="empty"):
        review_decision(p, "DEC001", "accepted", adapted=" ")
    review_decision(p, "DEC001", "accepted")
    assert p.approval.plan is False and p.approval.characters is True  # only the plan approval is affected


# ---- acknowledging warnings --------------------------------------------------------------------------------------------
def test_acknowledging_needs_a_reason_and_survives_a_recheck():
    p = planned()
    w = next(w for w in p.warnings if w.severity == Severity.ERROR)
    with pytest.raises(ReviewError, match="note is required"):
        acknowledge_warning(p, w.id)
    acknowledge_warning(p, w.id, note="the story does not say; Hari hands it back off-screen")
    from app.pipeline import check_continuity
    check_continuity(p)
    again = next(x for x in p.warnings if x.id == w.id)
    assert again.acknowledged and "off-screen" in again.ack_note and p.blocking_warnings == []
    with pytest.raises(ReviewError, match="unknown warning"):
        acknowledge_warning(p, "nope", note="x")


# ---- approval ---------------------------------------------------------------------------------------------------------------
def test_nothing_can_be_approved_without_a_plan_or_at_the_wrong_stage():
    p = ready_project()
    assert blockers(p, "characters") == [f"project is {p.status.value}; approval happens at plan_ready"]
    with pytest.raises(GateError, match="cannot approve"):
        approve(p, "characters")
    with pytest.raises(ReviewError):
        blockers(p, "everything")


def test_plan_approval_lists_every_unreviewed_decision():
    p = planned(decisions=[dec(adapted="a"), dec(adapted="b", original="o2")])
    b = blockers(p, "plan")
    assert "DEC001 has not been reviewed" in b and "DEC002 has not been reviewed" in b
    review_all(p)
    assert blockers(p, "plan") == []


def test_plan_approval_is_blocked_by_stale_scenes_and_plan_problems():
    p = planned()
    review_all(p)
    edit_plan_entity(p, "character", "CHAR_ANU", name_roman="Simran", name_native="ਸਿਮਰਨ")
    assert any("planned before a later edit" in b for b in blockers(p, "plan"))
    edit_plan_entity(p, "character", "CHAR_ANU", name_native="Anu")
    assert any("outside Gurmukhi" in b for b in blockers(p, "plan"))
    assert any("outside Gurmukhi" in b for b in blockers(p, "characters"))


def test_an_unexplained_costume_change_blocks_costume_approval_until_explained_or_acknowledged():
    p = planned()
    assert any("unexplained costume change" in b for b in blockers(p, "costumes"))
    edit_plan_entity(p, "costume", "COST_RAVI_02", change_reason="changes for the evening")
    assert blockers(p, "costumes") == []
    q = planned()
    w = next(w for w in q.warnings if w.code == "COSTUME_CHANGE_NO_REASON")
    acknowledge_warning(q, w.id, note="time passes between the scenes")
    assert blockers(q, "costumes") == []


def test_the_three_approvals_are_separate_and_the_last_one_is_blocked_by_an_unresolved_error():
    p = get_ready_to_approve()
    assert sorted(approve(p, "characters")["waiting_for"]) == ["costumes", "plan"]
    assert approve(p, "costumes")["waiting_for"] == ["plan"]
    out = approve(p, "plan")
    assert out["approved"] is False and "PROP_HOLDER_MISMATCH" in out["blocked_by"]  # the letter contradiction
    assert p.status == ProjectStatus.PLAN_READY and p.approval.complete
    w = next(w for w in p.warnings if w.severity == Severity.ERROR)
    acknowledge_warning(p, w.id, note="handed back off-screen")
    out = try_finalize(p)
    assert out["approved"] is True and p.status == ProjectStatus.APPROVED
    p.assert_can_generate_images()  # the gate is now open


def test_finalizing_applies_the_approved_plan_to_the_canonical_records_and_is_idempotent():
    p = get_ready_to_approve()
    acknowledge_warning(p, next(w.id for w in p.warnings if w.severity == Severity.ERROR), note="ok")
    for what in ("characters", "costumes", "plan"):
        approve(p, what)
    ravi = next(c for c in p.characters if c.id == "CHAR_RAVI")
    assert ravi.adapted_name and ravi.adapted_name_native and ravi.physical_description and ravi.approved
    cost = next(c for c in p.costumes if c.id == "COST_RAVI_02")
    assert cost.source_garments == "red checked shirt"  # the source wording is kept
    assert cost.garments.startswith("garment") and cost.change_reason  # the adapted description is in `garments`
    assert next(l for l in p.locations if l.id == "LOC_FAMILY_HOME").description == "courtyard house"
    before = p.model_dump(exclude={"created_at"})
    apply_plan_to_records(p)
    assert p.model_dump(exclude={"created_at"}) == before  # idempotent


def test_unapprove_one_keeps_the_others_and_steps_back_if_already_approved():
    p = get_ready_to_approve()
    acknowledge_warning(p, next(w.id for w in p.warnings if w.severity == Severity.ERROR), note="ok")
    for what in ("characters", "costumes", "plan"):
        approve(p, what)
    unapprove(p, "costumes")
    assert p.status == ProjectStatus.PLAN_READY
    assert p.approval.characters and p.approval.plan and not p.approval.costumes
    with pytest.raises(GateError):
        p.assert_can_generate_images()
    unapprove(p)
    assert not p.approval.characters


def test_keeping_a_stale_scene_plan_is_explicit_and_clears_the_block():
    p = planned()
    review_all(p)
    edit_plan_entity(p, "character", "CHAR_ANU", name_roman="Simran", name_native="ਸਿਮਰਨ")
    assert any("planned before a later edit" in b for b in blockers(p, "plan"))
    for sid in ["SC01", "SC03", "SC04"]:
        keep_scene_plan(p, sid)
    assert not any("planned before" in b for b in blockers(p, "plan"))
    with pytest.raises(ReviewError, match="not waiting"):
        keep_scene_plan(p, "SC02")
    assert any("kept the existing plan" in e for e in p.user_edits)  # it leaves a trace


def test_blockers_are_recomputed_so_a_stale_stored_problem_cannot_block_approval():
    p = planned()
    review_all(p)
    p.plan.problems = ["entity plan decision 13: something that was true once"]  # a stale stored list
    assert blockers(p, "plan") == []
    p.plan.entities.characters[0].name_native = "Latin name"  # a REAL problem, not yet in the stored list
    assert any("outside Gurmukhi" in b for b in blockers(p, "plan"))
