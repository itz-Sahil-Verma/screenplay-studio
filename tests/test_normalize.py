import json
from pathlib import Path

import pytest

from app.llm.fake import FakeLLM
from app.models import IntExt, Project, ProjectStatus, SceneExtraction, SourceScene, StateChangeKind
from app.pipeline import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "extracted_sample.json"  # real Azure output


def sample() -> Project:
    return normalize(Project.model_validate_json(FIXTURE.read_text()))


def make_project(*scenes: dict) -> Project:
    p = Project(status=ProjectStatus.EXTRACTED)
    for i, d in enumerate(scenes, 1):
        d = dict(d)
        heading = d.pop("heading", "INT. ROOM - DAY")
        d["scene_number"] = i
        d.setdefault("location", "room")
        p.source_scenes.append(SourceScene(
            number=i, heading=heading, text=f"{heading}\nscene {i}",
            extraction=SceneExtraction.model_validate(d)))
    return p


def ch(name, **kw):
    return {"name": name, **kw}


def proposal(**groups) -> str:
    return json.dumps({k: [{"ids": ids, "reason": "because"} for ids in v] for k, v in groups.items()})


# ---- on the real extraction (no LLM) -----------------------------------------------
def test_status_and_counts():
    p = sample()
    assert p.status == ProjectStatus.NORMALIZED
    assert len(p.characters) == 5 and len(p.locations) == 2 and len(p.scenes) == 4


def test_three_names_become_one_character():
    p = sample()
    ravi = [c for c in p.characters if c.id == "CHAR_RAVI"]
    assert len(ravi) == 1
    assert set(ravi[0].aliases) == {"R. Kumar", "the elder son"}
    assert ravi[0].scene_ids == ["SC01", "SC02", "SC03", "SC04"]


def test_no_duplicate_entities_case_insensitively():
    p = sample()
    for records in (p.characters, p.locations, p.props):
        names = [r.name.lower() for r in records]
        assert len(names) == len(set(names))
    assert len({c.id for c in p.costumes}) == len(p.costumes)


def test_recurring_location_is_one_record_with_sub_locations():
    home = next(l for l in sample().locations if l.id == "LOC_FAMILY_HOME")
    assert home.name == "Family home"  # display case, not the model's SHOUTING
    assert home.sub_locations == ["Kitchen", "Living room", "Courtyard"]
    assert home.scene_ids == ["SC01", "SC03", "SC04"]


def test_letter_is_one_prop_across_scenes_and_pot_is_present_in_its_scene():
    p = sample()
    letters = [x for x in p.props if "letter" in x.name]
    assert len(letters) == 1 and letters[0].scene_ids == ["SC01", "SC02", "SC04"]
    assert next(x for x in p.props if x.id == "PROP_POT").scene_ids == ["SC01"]
    assert "PROP_POT" in p.scenes[0].props_in  # set piece with no holder still counts as present


def test_costumes_are_created_once_and_carried_forward():
    p = sample()
    ravi = [c for c in p.costumes if c.character_id == "CHAR_RAVI"]
    assert [(c.garments, c.scene_ids) for c in ravi] == [
        ("blue jacket", ["SC01", "SC02"]),  # scene 2 doesn't say: inherited, not invented
        ("red checked shirt", ["SC03", "SC04"]),
    ]
    assert p.scenes[1].costumes["CHAR_RAVI"] == "COST_RAVI_01"
    assert p.scenes[2].costumes["CHAR_RAVI"] == "COST_RAVI_02"


def test_unexplained_costume_change_is_recorded_for_the_continuity_checker():
    p = sample()
    assert next(c for c in p.costumes if c.id == "COST_RAVI_02").change_reason == ""
    assert any("no story reason" in n for n in p.normalization_log)


def test_undescribed_characters_get_one_placeholder_costume():
    p = sample()
    meera = [c for c in p.costumes if c.character_id == "CHAR_MEERA"]
    assert len(meera) == 1 and meera[0].garments == "" and meera[0].scene_ids == ["SC01", "SC03", "SC04"]


def test_duplicate_events_collapse_and_items_resolve_to_prop_ids():
    p = sample()
    sc1 = [e for e in p.scenes[0].state_changes if e.kind.value.startswith("prop")]
    assert [(e.kind, e.character_id, e.item, e.to_character_id) for e in sc1] == [
        (StateChangeKind.PROP_TRANSFER, "CHAR_POSTMAN", "PROP_LETTER", "CHAR_RAVI")]
    sc3 = {(e.character_id, e.item) for e in p.scenes[2].state_changes if e.kind == StateChangeKind.PROP_GAIN}
    assert ("CHAR_RAVI", "PROP_HANDKERCHIEF") in sc3  # from "handkerchief tied around his palm"
    assert ("CHAR_MEERA", "PROP_CUP") in sc3  # from "cup of tea"


def test_prop_holders_use_canonical_ids_and_expose_the_planted_contradiction():
    p = sample()
    assert p.scenes[1].prop_holder_end["PROP_LETTER"] == "CHAR_UNCLE_HARI"
    assert p.scenes[3].prop_holder_start["PROP_LETTER"] == "CHAR_RAVI"  # Step 6 must flag this


def test_int_ext_comes_from_the_heading():
    p = sample()
    assert [s.int_ext for s in p.scenes] == [IntExt.INT, IntExt.EXT, IntExt.INT, IntExt.INT_EXT]


def test_every_reference_points_to_a_real_record():
    p = sample()
    chars, locs = {c.id for c in p.characters}, {l.id for l in p.locations}
    props, costs = {x.id for x in p.props}, {c.id for c in p.costumes}
    for s in p.scenes:
        assert s.location_id in locs
        assert set(s.characters) <= chars
        assert set(s.costumes) == set(s.characters) and set(s.costumes.values()) <= costs
        assert set(s.prop_holder_start) | set(s.prop_holder_end) <= props
        for h in [*s.prop_holder_start.values(), *s.prop_holder_end.values()]:
            assert h in chars or h.startswith("@")
        for e in s.state_changes:
            assert e.character_id in chars
    assert all(c.character_id in chars for c in p.costumes)


def test_source_text_is_kept_on_each_scene_for_traceability():
    p = sample()
    assert "POSTMAN" in p.scenes[0].source_text and p.scenes[0].source_text == p.source_scenes[0].text


def test_rerunning_gives_identical_ids():
    a = sample()
    b = normalize(a.model_copy(deep=True))
    assert b.model_dump(exclude={"created_at"}) == a.model_dump(exclude={"created_at"})


def test_refuses_unextracted_or_missing_scenes():
    p = Project.model_validate_json(FIXTURE.read_text())
    p.source_scenes[1].extraction = None
    with pytest.raises(ValueError, match=r"\[2\]"):
        normalize(p)
    with pytest.raises(ValueError):
        normalize(Project())  # status is created


# ---- model proposals are validated by code ---------------------------------------
def test_safe_model_merge_is_applied_and_logged():
    p = make_project({"characters": [ch("Ma")]}, {"characters": [ch("Meera")]})
    normalize(p, FakeLLM([proposal(characters=[["C1", "C2"]])]))
    assert len(p.characters) == 1
    assert any("MERGED characters" in n and "proposed by model" in n for n in p.normalization_log)


def test_merge_of_characters_who_share_a_scene_is_rejected():
    p = make_project({"characters": [ch("Ravi"), ch("Ravindra")]})
    normalize(p, FakeLLM([proposal(characters=[["C1", "C2"]])]))
    assert len(p.characters) == 2
    assert any("REJECTED" in n and "appear together" in n for n in p.normalization_log)


def test_unknown_and_double_used_labels_are_rejected():
    p = make_project({"characters": [ch("A")]}, {"characters": [ch("B")]}, {"characters": [ch("C")]})
    normalize(p, FakeLLM([proposal(characters=[["C1", "C9"], ["C1", "C2"], ["C2", "C3"]])]))
    log = " ".join(p.normalization_log)
    assert "unknown label" in log
    # [C1,C9] rejected (unknown label); [C1,C2] applied; [C2,C3] rejected (C2 already used) -> C stays separate
    assert sorted(c.name for c in p.characters) == ["A", "C"]
    assert next(c for c in p.characters if c.name == "A").aliases == ["B"]
    assert "already in another group" in log


def test_costume_descriptions_of_one_garment_can_be_merged():
    def scenes(who):  # different names => different prompts => no cache hit between the two runs
        return ({"characters": [ch(who, costume="red shirt")]}, {"characters": [ch(who, costume="red checked shirt")]})

    unmerged = normalize(make_project(*scenes("RAVI")), FakeLLM([proposal()]))
    assert len(unmerged.costumes) == 2
    merged = normalize(make_project(*scenes("KIRAN")), FakeLLM([proposal(costumes=[["K1", "K2"]])]))
    assert len(merged.costumes) == 1 and merged.costumes[0].scene_ids == ["SC01", "SC02"]


def test_costume_merge_across_different_characters_is_rejected():
    scenes = ({"characters": [ch("A", costume="red"), ch("B", costume="green")]},
              {"characters": [ch("A", costume="blue"), ch("B", costume="yellow")]})
    p = normalize(make_project(*scenes), FakeLLM([proposal(costumes=[["K1", "K3"]])]))
    assert len(p.costumes) == 4 and any("different characters" in n for n in p.normalization_log)


def test_model_failure_does_not_break_normalization():
    p = make_project({"characters": [ch("A")]}, {"characters": [ch("B")]})
    normalize(p, FakeLLM([RuntimeError("down")]))
    assert p.status == ProjectStatus.NORMALIZED and len(p.characters) == 2
    assert any("unavailable" in n for n in p.normalization_log)


def test_invalid_model_json_falls_back_to_deterministic():
    p = make_project({"characters": [ch("A")]}, {"characters": [ch("B")]})
    llm = FakeLLM(["nope", "nope", "nope"])
    normalize(p, llm)
    assert len(llm.calls) == 3 and len(p.characters) == 2
    assert any("not valid JSON" in n for n in p.normalization_log)


def test_no_model_call_when_nothing_could_be_merged():
    p = make_project({"characters": [ch("A")]})
    llm = FakeLLM([])  # any call raises
    normalize(p, llm)
    assert llm.calls == []


def test_model_proposal_is_cached():
    scenes = ({"characters": [ch("Ma")]}, {"characters": [ch("Meera")]})
    normalize(make_project(*scenes), FakeLLM([proposal(characters=[["C1", "C2"]])]))
    second = FakeLLM([])
    p = normalize(make_project(*scenes), second)
    assert second.calls == [] and len(p.characters) == 1


def test_transfer_implies_gain_and_loss_and_exact_duplicates_vanish():
    ev = lambda kind, who, item, to="": {"kind": kind, "character": who, "item": item, "to_character": to}
    p = make_project({
        "characters": [ch("A"), ch("B")],
        "props": [{"name": "letter"}],
        "events": [ev("prop_transfer", "A", "letter", "B"), ev("prop_transfer", "A", "letter", "B"),
                   ev("prop_gain", "B", "letter"), ev("prop_loss", "A", "letter"),
                   ev("knowledge_gain", "B", "the plan")],
    })
    normalize(p)
    kinds = [e.kind for e in p.scenes[0].state_changes]
    assert kinds == [StateChangeKind.PROP_TRANSFER, StateChangeKind.KNOWLEDGE_GAIN]


def test_events_about_unknown_people_or_kinds_are_skipped_and_logged():
    p = make_project({"characters": [ch("A")], "events": [
        {"kind": "prop_gain", "character": "Nobody", "item": "x"},
        {"kind": "teleport", "character": "A", "item": "x"}]})
    normalize(p)
    assert p.scenes[0].state_changes == []
    assert sum("skipped" in n for n in p.normalization_log) == 2


def test_character_described_late_keeps_one_costume_from_the_start():
    p = normalize(make_project({"characters": [ch("A")]}, {"characters": [ch("A", costume="green kurta")]}))
    assert len(p.costumes) == 1 and p.costumes[0].scene_ids == ["SC01", "SC02"]
