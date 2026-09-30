import json

import pytest

from app.ingestion import read_document
from app.llm import LLMError, generate_structured
from app.llm.fake import FakeLLM
from app.models import Project, ProjectStatus, SceneExtraction, SourceScene
from app.pipeline import extract_scene, prepare_source, run_extraction, verify_extraction

TEXT = """INT. KITCHEN - MORNING

MEERA (58) stirs a pot. RAVI (32) enters in a BLUE JACKET and pockets a LETTER. He leaves.

INT. ROAD - DAY

RAVI hands the LETTER to UNCLE HARI, who keeps it. Ravi cuts his palm and leaves.

INT. LIVING ROOM - EVENING

MEERA and RAVI sit in silence. Ravi wears a RED SHIRT. Anu brings tea to Meera.
"""


def ok(number=1, chars=("MEERA", "RAVI"), props=("LETTER",)):
    return json.dumps({
        "scene_number": number,
        "characters": [{"name": c} for c in chars],
        "props": [{"name": p} for p in props],
    })


def project() -> Project:
    p = Project()
    prepare_source(p, read_document(TEXT.encode(), "s.txt").text)
    return p


def test_prepare_source_splits_by_code():
    p = project()
    assert [s.number for s in p.source_scenes] == [1, 2, 3]


def test_success_moves_project_to_extracted():
    p = project()
    llm = FakeLLM([ok(1), ok(2, ("RAVI", "UNCLE HARI")), ok(3, props=())])
    run_extraction(p, llm)
    assert p.status == ProjectStatus.EXTRACTED
    assert all(s.extraction for s in p.source_scenes)


def test_code_owns_scene_numbers_even_if_model_is_wrong():
    p = project()
    extract_scene(p, 2, FakeLLM([ok(number=99, chars=("RAVI",))]))
    assert p.source_scenes[1].extraction.scene_number == 2


def test_invalid_json_is_retried_with_the_error_fed_back():
    llm = FakeLLM(["not json at all", ok(1)])
    out = generate_structured(llm, "sys", "prompt", SceneExtraction)
    assert out.scene_number == 1
    assert "rejected" in llm.calls[1]["prompt"]


def test_gives_up_after_max_retries():
    with pytest.raises(LLMError):
        generate_structured(FakeLLM(["x", "y", "z"]), "s", "p", SceneExtraction, max_retries=3)


def test_invented_character_is_caught():
    p = project()
    ex = SceneExtraction.model_validate_json(ok(1, chars=("MEERA", "PRIYA")))
    problems = verify_extraction(p.source_scenes[0], ex)
    assert any("PRIYA" in m for m in problems)


def test_invented_character_triggers_retry_with_feedback_then_passes():
    p = project()
    llm = FakeLLM([ok(1, chars=("MEERA", "PRIYA")), ok(1)])
    extract_scene(p, 1, llm)
    assert "PRIYA" in llm.calls[1]["prompt"]
    assert p.source_scenes[0].extraction is not None
    assert not any("PRIYA" in m for m in p.all_problems)  # retry fixed it


def test_persistent_hallucination_is_kept_but_flagged():
    p = project()
    extract_scene(p, 1, FakeLLM([ok(1, chars=("PRIYA",))] * 2), max_calls=2)
    assert any("PRIYA" in m for m in p.source_scenes[0].problems)
    assert any("PRIYA" in m for m in p.all_problems)


def test_failed_scene_is_recorded_and_only_it_is_retried():
    p = project()
    llm = FakeLLM([ok(1), RuntimeError("boom"), ok(3, props=())])
    run_extraction(p, llm)
    assert p.status == ProjectStatus.CREATED  # not advanced: scene 2 failed
    assert p.source_scenes[1].error.startswith("RuntimeError")
    assert p.source_scenes[0].extraction and p.source_scenes[2].extraction

    retry = FakeLLM([ok(2, ("RAVI", "UNCLE HARI"))])
    run_extraction(p, retry)
    assert len(retry.calls) == 1  # scenes 1 and 3 were not redone
    assert p.status == ProjectStatus.EXTRACTED
    assert p.source_scenes[1].error == ""


# ---- event checks, cache, persistence ---------------------------------------
def ex_with_events(events):
    return SceneExtraction.model_validate({
        "scene_number": 1,
        "characters": [{"name": "MEERA"}],
        "events": events,
    })


def test_event_without_item_is_rejected():
    p = project()
    ex = ex_with_events([{"kind": "knowledge_gain", "character": "MEERA", "item": ""}])
    assert any("empty item" in m for m in verify_extraction(p.source_scenes[0], ex))


def test_unknown_event_kind_and_transfer_without_target_are_rejected():
    p = project()
    ex = ex_with_events([
        {"kind": "teleport", "character": "MEERA", "item": "x"},
        {"kind": "prop_transfer", "character": "MEERA", "item": "letter"},
    ])
    problems = verify_extraction(p.source_scenes[0], ex)
    assert any("teleport" in m for m in problems)
    assert any("no to_character" in m for m in problems)


def test_complete_event_passes():
    p = project()
    ex = ex_with_events([{"kind": "knowledge_gain", "character": "MEERA", "item": "Ravi has a job offer"}])
    assert not any("event" in m for m in verify_extraction(p.source_scenes[0], ex))


def test_empty_item_from_model_triggers_retry_with_feedback():
    p = project()
    bad = json.dumps({"scene_number": 1, "characters": [{"name": "MEERA"}],
                      "events": [{"kind": "knowledge_gain", "character": "MEERA", "item": ""}]})
    good = json.dumps({"scene_number": 1, "characters": [{"name": "MEERA"}],
                       "events": [{"kind": "knowledge_gain", "character": "MEERA", "item": "the offer"}]})
    llm = FakeLLM([bad, good])
    extract_scene(p, 1, llm)
    assert "empty item" in llm.calls[1]["prompt"]
    assert p.source_scenes[0].extraction.events[0].item == "the offer"


def test_verified_result_is_cached_and_reused_without_llm_call():
    p1, p2 = project(), project()
    first = FakeLLM([ok(1)])
    extract_scene(p1, 1, first)
    second = FakeLLM([])  # any call would raise AssertionError
    extract_scene(p2, 1, second)
    assert second.calls == []
    assert p2.source_scenes[0].extraction == p1.source_scenes[0].extraction


def test_unverified_result_is_not_cached():
    bad = ok(1, chars=("PRIYA",))
    extract_scene(project(), 1, FakeLLM([bad, bad]))
    again = FakeLLM([ok(1)])
    extract_scene(project(), 1, again)
    assert len(again.calls) == 1  # had to call the model: the bad result was not cached


def test_cache_is_per_model():
    a = FakeLLM([ok(1)])
    a.deployment = "gpt-4.1-mini"
    extract_scene(project(), 1, a)
    b = FakeLLM([ok(1)])
    b.deployment = "gpt-5"
    extract_scene(project(), 1, b)
    assert len(b.calls) == 1  # different model, so no cache hit


def test_project_roundtrips_on_disk():
    from app.storage import load_project, save_project

    p = project()
    extract_scene(p, 1, FakeLLM([ok(1)]))
    save_project(p)
    restored = load_project(p.id)
    assert restored.source_scenes[0].extraction.characters[0].name == "MEERA"
    assert restored.id == p.id


# ---- one retry budget per scene; problems never accumulate ---------------------
def test_budget_is_total_model_calls_across_both_failure_kinds():
    p = project()
    llm = FakeLLM(["not json", ok(1, chars=("PRIYA",)), ok(1, chars=("PRIYA",)), ok(1)])
    extract_scene(p, 1, llm, max_calls=3)
    assert len(llm.calls) == 3  # the 4th (good) response was never requested
    assert p.source_scenes[0].extraction is not None  # last parseable answer kept...
    assert any("PRIYA" in m for m in p.source_scenes[0].problems)  # ...and flagged


def test_all_invalid_json_stops_at_budget_and_records_error():
    p = project()
    llm = FakeLLM(["x", "y", "z", "w"])
    extract_scene(p, 1, llm, max_calls=3)
    assert len(llm.calls) == 3
    assert p.source_scenes[0].extraction is None
    assert "no valid output after 3" in p.source_scenes[0].error


def test_default_budget_comes_from_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_max_retries", 1)
    p = project()
    llm = FakeLLM(["x", "y"])
    extract_scene(p, 1, llm)
    assert len(llm.calls) == 1


def test_generate_structured_default_budget_comes_from_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_max_retries", 2)
    llm = FakeLLM(["x", "y", "z"])
    with pytest.raises(LLMError):
        generate_structured(llm, "s", "p", SceneExtraction)
    assert len(llm.calls) == 2


def test_reextracting_replaces_problems_instead_of_accumulating():
    p = project()
    bad = ok(1, chars=("PRIYA",))
    extract_scene(p, 1, FakeLLM([bad]), max_calls=1)
    extract_scene(p, 1, FakeLLM([bad]), max_calls=1)
    priya = [m for m in p.all_problems if "PRIYA" in m]
    assert len(priya) == 1  # not 2


def test_stale_problems_disappear_after_a_successful_retry():
    p = project()
    extract_scene(p, 1, FakeLLM([ok(1, chars=("PRIYA",))]), max_calls=1)
    assert p.source_scenes[0].problems
    extract_scene(p, 1, FakeLLM([ok(1)]), max_calls=1)
    assert p.source_scenes[0].problems == []
    assert not any("PRIYA" in m for m in p.all_problems)


def test_failed_scene_shows_in_all_problems_then_clears_on_success():
    p = project()
    extract_scene(p, 2, FakeLLM([RuntimeError("boom")]))
    assert any("scene 2: extraction failed" in m for m in p.all_problems)
    extract_scene(p, 2, FakeLLM([ok(2, ("RAVI", "UNCLE HARI"))]))
    assert not any("scene 2" in m for m in p.all_problems)


def test_prepare_source_twice_does_not_duplicate_source_problems():
    p = Project()
    text = "no headings here, just a short paragraph"
    prepare_source(p, text)
    prepare_source(p, text)
    assert len(p.extraction_problems) == len(set(p.extraction_problems))


# ---- grounding uses whole words ----------------------------------------------
def test_name_inside_a_longer_word_is_not_grounded():
    scene = SourceScene(number=1, text="The channel was noisy and RAVI listened.")
    ex = SceneExtraction.model_validate({"scene_number": 1, "characters": [{"name": "ANN"}, {"name": "RAVI"}]})
    problems = verify_extraction(scene, ex)
    assert any("ANN" in m for m in problems) and not any("RAVI" in m for m in problems)


def test_prop_plural_and_singular_both_ground():
    scene = SourceScene(number=1, text="RAVI lifts two cups and a LETTER.")
    ex = SceneExtraction.model_validate({
        "scene_number": 1, "characters": [{"name": "RAVI"}],
        "props": [{"name": "cup"}, {"name": "letters"}, {"name": "spaceship"}],
    })
    problems = verify_extraction(scene, ex)
    assert [m for m in problems if "prop" in m] == ["prop 'spaceship' does not appear in the scene text"]


def test_multiword_and_punctuated_names_ground():
    scene = SourceScene(number=1, text="\"R. KUMAR?\" says Uncle Hari.")
    ex = SceneExtraction.model_validate({"scene_number": 1, "characters": [{"name": "R. Kumar"}, {"name": "UNCLE HARI"}]})
    assert verify_extraction(scene, ex) == []
