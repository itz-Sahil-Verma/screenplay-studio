import pytest

from app.models import (
    Asset,
    AssetKind,
    AssetStatus,
    ContinuityWarning,
    CultureSelection,
    GateError,
    InvalidTransition,
    Project,
    ProjectStatus,
    Scene,
    Severity,
    spec_hash,
)


def plan_ready_project() -> Project:
    p = Project(selection=CultureSelection(pack_id="majhi_punjabi", region="Amritsar", setting="rural", output_script="gurmukhi"))
    for s in (
        ProjectStatus.EXTRACTED,
        ProjectStatus.NORMALIZED,
        ProjectStatus.PLAN_READY,
    ):
        p.transition(s)
    return p


def test_transitions_only_go_forward_one_step():
    p = Project()
    with pytest.raises(InvalidTransition):
        p.transition(ProjectStatus.APPROVED)
    p.transition(ProjectStatus.EXTRACTED)
    assert p.status == ProjectStatus.EXTRACTED


def test_cannot_approve_without_all_three_approvals():
    p = plan_ready_project()
    with pytest.raises(GateError):
        p.approve()


def test_unacknowledged_error_blocks_approval_until_acknowledged():
    p = plan_ready_project()
    p.approval.characters = p.approval.plan = p.approval.costumes = p.continuity_checked = True
    w = ContinuityWarning(code="PROP_VANISHED", severity=Severity.ERROR, message="x")
    p.warnings.append(w)
    with pytest.raises(GateError):
        p.approve()
    w.acknowledged = True
    p.approve()
    assert p.status == ProjectStatus.APPROVED


def test_images_blocked_before_approval():
    p = plan_ready_project()
    with pytest.raises(GateError):
        p.assert_can_generate_images()


def test_images_allowed_after_approval():
    p = plan_ready_project()
    p.approval.characters = p.approval.plan = p.approval.costumes = p.continuity_checked = True
    p.approve()
    p.assert_can_generate_images()  # does not raise


def test_reopen_closes_gate_and_marks_generated_assets_stale():
    p = plan_ready_project()
    p.approval.characters = p.approval.plan = p.approval.costumes = p.continuity_checked = True
    p.approve()
    p.assets.append(
        Asset(id="A1", kind=AssetKind.CHARACTER_REF, entity_id="CHAR_X", status=AssetStatus.GENERATED)
    )
    p.assets.append(
        Asset(id="A2", kind=AssetKind.CHARACTER_REF, entity_id="CHAR_Y", status=AssetStatus.FAILED)
    )
    p.reopen()
    assert p.status == ProjectStatus.PLAN_READY
    assert not p.approval.complete
    assert p.asset("A1").status == AssetStatus.STALE
    assert p.asset("A2").status == AssetStatus.FAILED  # untouched
    with pytest.raises(GateError):
        p.assert_can_generate_images()


def test_spec_hash_is_stable_and_order_independent():
    assert spec_hash({"a": 1, "b": 2}) == spec_hash({"b": 2, "a": 1})
    assert spec_hash({"a": 1}) != spec_hash({"a": 2})


def test_project_roundtrips_through_json():
    p = plan_ready_project()
    p.scenes.append(Scene(scene_id="SC01", number=1, costumes={"CHAR_A": "COST_A_01"}))
    restored = Project.model_validate_json(p.model_dump_json())
    assert restored.scene("SC01").costume_ids == ["COST_A_01"]
    assert restored.status == ProjectStatus.PLAN_READY


def test_cannot_approve_or_generate_before_continuity_check_has_run():
    p = plan_ready_project()
    p.approval.characters = p.approval.plan = p.approval.costumes = True
    with pytest.raises(GateError, match="continuity"):
        p.approve()
