import json
from pathlib import Path

import pytest

from app.culture_packs.loader import load_pack, load_scripts
from app.llm.fake import FakeLLM
from app.models import (CulturePack, CultureSelection, Fact, Project, ProjectStatus, ReviewStatus, Source)
from app.pipeline import build_plan, check_continuity, normalize, replan_entities, replan_scene
from app.pipeline.plan import entity_prompt, flatten_decisions, verify_entity_plan

FIXTURE = Path(__file__).parent / "fixtures" / "extracted_sample.json"
NATIVE = ["ਮੀਰਾ", "ਰਵੀ", "ਅਨੂ", "ਡਾਕੀਆ", "ਹਰੀ ਸਿੰਘ"]  # test data only, in Gurmukhi
SCENES = ["SC01", "SC02", "SC03", "SC04"]


def ready_project() -> Project:
    p = normalize(Project.model_validate_json(FIXTURE.read_text()))
    check_continuity(p)
    p.selection = CultureSelection(pack_id="majhi_punjabi", region="Amritsar", setting="rural", output_script="gurmukhi")
    return p


def dec(entity="", basis="judgment", facts=(), uncertain=False, adapted="adapted", original="orig", dim="character"):
    return {"dimension": dim, "entity_id": entity, "original": original, "adapted": adapted, "reason": "because",
            "basis": basis, "fact_ids": list(facts), "uncertain": uncertain}


def entity_json(p: Project, mutate=None, decisions=None) -> str:
    d = {
        "season_and_period": "dry winter, present day",
        "characters": [{"character_id": c.id, "name_roman": f"Name{i}", "name_native": NATIVE[i % 5],
                        "appearance": "lean, grey at the temples", "grooming": "trimmed beard"}
                       for i, c in enumerate(p.characters)],
        "costumes": [{"costume_id": c.id, "garments": f"garment {i}", "colours": f"colour {i}"}
                     for i, c in enumerate(p.costumes)],
        "locations": [{"location_id": l.id, "name_roman": l.name, "description": "courtyard house"} for l in p.locations],
        "props": [{"prop_id": x.id, "name_roman": x.name, "name_native": "ਚਿੱਠੀ"} for x in p.props],
        "decisions": decisions if decisions is not None else [dec("CHAR_RAVI", adapted="Name1")],
    }
    if mutate:
        mutate(d)
    return json.dumps(d, ensure_ascii=False)


def scene_json(sid: str, decisions=None, **over) -> str:
    d = {"scene_id": sid, "dialogue_notes": "use tusi for elders", "gestures": ["touch feet"],
         "decisions": decisions if decisions is not None else []}
    d.update(over)
    return json.dumps(d)


def happy(p: Project, **kw) -> FakeLLM:
    return FakeLLM([entity_json(p, **kw)] + [scene_json(s) for s in SCENES])


# ---- happy path -----------------------------------------------------------------------------------
def test_full_plan_reaches_plan_ready_with_everything_covered():
    p = ready_project()
    llm = happy(p)
    build_plan(p, llm)
    assert p.status == ProjectStatus.PLAN_READY and p.plan.problems == []
    assert len(llm.calls) == 5  # one entity call + one per scene
    assert set(p.plan.scenes) == set(SCENES)


def test_decisions_get_ids_source_scenes_and_carry_the_basis():
    p = ready_project()
    llm = FakeLLM([entity_json(p, decisions=[dec("CHAR_RAVI", basis="pack", facts=["F016"], adapted="Name1")])]
                  + [scene_json("SC01", [dec("PROP_LETTER", dim="story_world")])] + [scene_json(s) for s in SCENES[1:]])
    build_plan(p, llm)
    d1, d2 = p.decisions
    assert (d1.id, d2.id) == ("DEC001", "DEC002")
    assert d1.source_scene_ids == ["SC01", "SC02", "SC03", "SC04"]  # Ravi's scenes, derived by code
    assert d2.source_scene_ids == ["SC01"] and d1.basis == "pack" and d1.fact_ids == ["F016"]


def test_approval_is_reset_when_the_plan_is_built():
    p = ready_project()
    p.approval.plan = True
    build_plan(p, happy(p))
    assert not p.approval.plan


# ---- uncertainty is propagated by code -----------------------------------------------------------------
def test_a_decision_relying_on_a_flagged_fact_becomes_uncertain_automatically():
    p = ready_project()
    pack = load_pack("majhi_punjabi")
    flagged = next(f.id for f in pack.facts if f.flagged)
    solid = next(f.id for f in pack.facts if not f.flagged)
    build_plan(p, happy(p, decisions=[dec(basis="pack", facts=[flagged]), dec(basis="pack", facts=[solid], adapted="b")]))
    a, b = p.decisions
    assert a.uncertain and flagged in a.uncertain_reason
    assert not b.uncertain and b.uncertain_reason == ""


def test_model_declared_uncertainty_is_kept():
    p = ready_project()
    build_plan(p, happy(p, decisions=[dec(uncertain=True)]))
    assert p.decisions[0].uncertain and "model" in p.decisions[0].uncertain_reason


# ---- the verifier rejects bad plans and the model is told why --------------------------------------------
def test_missing_id_is_rejected_then_fixed_via_feedback():
    p = ready_project()
    bad = entity_json(p, mutate=lambda d: d["props"].pop())
    llm = FakeLLM([bad, entity_json(p)] + [scene_json(s) for s in SCENES])
    build_plan(p, llm)
    assert "missing entries" in llm.calls[1]["prompt"] and p.plan.problems == []


def test_invented_and_duplicate_ids_are_rejected():
    p = ready_project()
    d = json.loads(entity_json(p))
    d["characters"].append({**d["characters"][0]})
    d["props"].append({"prop_id": "PROP_UNICORN", "name_roman": "u", "name_native": "ਯ"})
    problems = verify_entity_plan(p, load_pack("majhi_punjabi"), load_scripts()["gurmukhi"],
                                  __import__("app.models", fromlist=["EntityPlan"]).EntityPlan.model_validate(d))
    text = " ".join(problems)
    assert "PROP_UNICORN" in text and "more than one entry" in text


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d["characters"][0].update(name_native="Ravi"), "outside Gurmukhi"),
    (lambda d: d["characters"][1].update(name_native=d["characters"][0]["name_native"], name_roman=d["characters"][0]["name_roman"]), "same name"),
    (lambda d: d["characters"][0].update(appearance=""), "empty appearance"),
    (lambda d: d["costumes"][1].update(garments=d["costumes"][0]["garments"], colours=d["costumes"][0]["colours"]), "identical"),
    (lambda d: d["locations"][0].update(description=""), "empty description"),
])
def test_entity_plan_problems_are_detected(mutate, expect):
    p = ready_project()
    from app.models import EntityPlan
    plan = EntityPlan.model_validate_json(entity_json(p, mutate=mutate))
    # the two costumes being compared must belong to the same character for 'identical' to apply
    if expect == "identical":
        ravi = [c.id for c in p.costumes if c.character_id == "CHAR_RAVI"]
        idx = {c.id: i for i, c in enumerate(p.costumes)}
        plan.costumes[idx[ravi[1]]].garments = plan.costumes[idx[ravi[0]]].garments
        plan.costumes[idx[ravi[1]]].colours = plan.costumes[idx[ravi[0]]].colours
    problems = verify_entity_plan(p, load_pack("majhi_punjabi"), load_scripts()["gurmukhi"], plan)
    assert any(expect in m for m in problems), problems


def test_decision_checks_fact_ids_and_basis():
    p = ready_project()
    build_plan(p, FakeLLM([entity_json(p, decisions=[
        dec(basis="pack", facts=["F999"]), dec(basis="pack", facts=[])])] * 3))
    text = " ".join(p.plan.problems)
    assert "F999" in text and "no fact_ids" in text


def test_a_made_up_entity_id_leaves_the_decision_unlinked_instead_of_failing_the_plan():
    """Found on a live run: the model wrote entity_id 'etiquette'. That must not block approval."""
    p = ready_project()
    llm = FakeLLM([entity_json(p, decisions=[dec(entity="etiquette"), dec(entity="CHAR_RAVI", original="o2")])]
                  + [scene_json(s) for s in SCENES])
    build_plan(p, llm)
    assert p.plan.problems == [] and p.status == ProjectStatus.PLAN_READY
    assert len(llm.calls) == 5  # no wasted retry either
    made_up, real = p.decisions
    assert made_up.entity_id is None and made_up.source_scene_ids == ["SC01", "SC02", "SC03", "SC04"]
    assert real.entity_id == "CHAR_RAVI"


def test_scene_plan_needs_dialogue_notes_and_gestures():
    p = ready_project()
    llm = FakeLLM([entity_json(p)] + [scene_json("SC01", dialogue_notes="", gestures=[])] * 3 + [scene_json(s) for s in SCENES[1:]])
    build_plan(p, llm)
    assert any("SC01" in m and "dialogue_notes" in m for m in p.plan.problems)  # kept but flagged after the budget ran out


# ---- failure isolation, re-planning, review state ------------------------------------------------------------
def test_one_failing_scene_does_not_lose_the_rest_and_only_it_is_redone():
    p = ready_project()
    llm = FakeLLM([entity_json(p), scene_json("SC01"), RuntimeError("boom"), scene_json("SC03"), scene_json("SC04")])
    build_plan(p, llm)
    assert p.status == ProjectStatus.NORMALIZED  # not complete: stays put
    assert "SC02" in p.plan.failed_scenes and set(p.plan.scenes) == {"SC01", "SC03", "SC04"}
    assert any("SC02" in m and "planning failed" in m for m in p.plan.problems)

    retry = FakeLLM([scene_json("SC02")])
    build_plan(p, retry)
    assert len(retry.calls) == 1  # entity plan and other scenes were not redone
    assert p.status == ProjectStatus.PLAN_READY and p.plan.failed_scenes == {} and p.plan.problems == []


def test_replan_scene_redoes_only_that_scene():
    p = ready_project()
    build_plan(p, happy(p))
    one = FakeLLM([scene_json("SC03", [dec("CHAR_MEERA", adapted="new")])])
    replan_scene(p, "SC03", one)
    assert len(one.calls) == 1 and any(d.adapted == "new" for d in p.decisions)


def test_replanning_entities_drops_scene_plans_because_names_changed():
    p = ready_project()
    build_plan(p, happy(p))
    def rename(d):
        d["characters"][0]["name_roman"] = "Renamed"
        d["characters"][0]["name_native"] = "ਨਵਾਂ"

    llm = FakeLLM([entity_json(p, mutate=rename, decisions=[dec(adapted="different")])] + [scene_json(s) for s in SCENES])
    replan_entities(p, llm)
    assert len(llm.calls) == 5 and p.decisions[0].adapted == "different"  # new names => new scene prompts => all redone
    assert "Renamed" in llm.calls[1]["prompt"]  # the scene calls saw the new names


def test_replanning_entities_reuses_cached_scenes_when_nothing_they_depend_on_changed():
    p = ready_project()
    build_plan(p, happy(p))
    llm = FakeLLM([entity_json(p, decisions=[dec(adapted="different")])])  # only decision text differs
    replan_entities(p, llm)
    assert len(llm.calls) == 1 and set(p.plan.scenes) == set(SCENES)


def test_review_state_survives_regeneration_only_for_unchanged_decisions():
    p = ready_project()
    build_plan(p, happy(p, decisions=[dec(adapted="keep"), dec(adapted="change", original="o2")]))
    p.decisions[0].status, p.decisions[0].reviewer_note = ReviewStatus.ACCEPTED, "checked"
    p.decisions[1].status = ReviewStatus.ACCEPTED
    replan_entities(p, FakeLLM([entity_json(p, decisions=[dec(adapted="keep"), dec(adapted="CHANGED", original="o2")])]
                               + [scene_json(s) for s in SCENES]))
    assert p.decisions[0].status == ReviewStatus.ACCEPTED and p.decisions[0].reviewer_note == "checked"
    assert p.decisions[1].status == ReviewStatus.PROPOSED  # its content changed: needs a fresh review


# ---- preconditions ------------------------------------------------------------------------------------------------
def test_preconditions():
    p = ready_project()
    p.selection = None
    with pytest.raises(ValueError, match="no culture"):
        build_plan(p, FakeLLM([]))
    p = ready_project()
    p.continuity_checked = False
    with pytest.raises(ValueError, match="continuity"):
        build_plan(p, FakeLLM([]))
    p = ready_project()
    p.selection.region = "Ludhiana"
    with pytest.raises(ValueError, match="region"):
        build_plan(p, FakeLLM([]))
    p = ready_project()
    p.status = ProjectStatus.EXTRACTED
    with pytest.raises(ValueError, match="normalized"):
        build_plan(p, FakeLLM([]))


# ---- isolation and genericity ---------------------------------------------------------------------------------------
def other_pack() -> CulturePack:
    return CulturePack(
        id="other", culture="Testlandic", regions=["Amritsar"], settings=["rural"], supported_scripts=["gurmukhi"],
        default_script="gurmukhi", sources=[Source(id="S1", title="t", url="http://x")],
        facts=[Fact(id="F1", category="food", text="SECRET-OTHER-CULTURE-FACT", source_ids=["S1"], basis="page_read", confidence="high")])


def test_prompts_contain_only_the_selected_pack_and_no_hardcoded_culture_names():
    p = ready_project()
    p.selection.pack_id = "other"
    llm = FakeLLM([entity_json(p, decisions=[dec(basis="pack", facts=["F1"])])] + [scene_json(s) for s in SCENES])
    build_plan(p, llm, pack=other_pack())
    for call in llm.calls:
        blob = call["system"] + call["prompt"]
        assert "SECRET-OTHER-CULTURE-FACT" in blob  # the selected pack is used
        assert "Majhi" not in call["system"] and "Punjabi" not in call["system"]  # no culture baked into the instructions
        assert "CULTURE: Testlandic" in call["prompt"]


def test_entity_prompt_lists_required_ids_and_flags_uncertain_facts():
    p = ready_project()
    prompt = entity_prompt(p, load_pack("majhi_punjabi"), load_scripts())
    assert "REQUIRED IDS" in prompt and "CHAR_RAVI" in prompt and "COST_RAVI_02" in prompt
    assert "[UNCERTAIN" in prompt and "Gurmukhi" in prompt
    assert "the letter" in prompt  # the continuity issue is passed along


def test_regenerate_bypasses_the_cache_but_writes_the_new_answer():
    p = ready_project()
    build_plan(p, happy(p))
    fresh = FakeLLM([scene_json("SC02", [dec(adapted="second take")])])
    replan_scene(p, "SC02", fresh)
    assert len(fresh.calls) == 1  # a cache hit would have made 0 calls
    later = ready_project()
    build_plan(later, FakeLLM([]))  # the cache now holds the regenerated SC02...
    assert any(d.adapted == "second take" for d in later.decisions)  # ...and the untouched pieces


def test_verified_plans_are_cached():
    p = ready_project()
    build_plan(p, happy(p))
    q = ready_project()
    again = FakeLLM([])  # any call would raise
    build_plan(q, again)
    assert again.calls == [] and q.status == ProjectStatus.PLAN_READY


# ---- language, script and name hygiene (found on the first live run) ------------------------------
GURMUKHI_SENTENCE = "ਰਵੀ ਆਪਣੀ ਮਾਂ ਨੂੰ ਆਦਰ ਨਾਲ ਬੁਲਾਉਂਦਾ ਹੈ"


def problems_for(p, mutate):
    from app.models import EntityPlan
    return verify_entity_plan(p, load_pack("majhi_punjabi"), load_scripts()["gurmukhi"],
                              EntityPlan.model_validate_json(entity_json(p, mutate=mutate)))


def test_reasons_and_descriptions_must_be_english_not_the_output_script():
    p = ready_project()
    text = " ".join(problems_for(p, lambda d: (d["decisions"][0].update(reason=GURMUKHI_SENTENCE),
                                                d["costumes"][0].update(garments=GURMUKHI_SENTENCE),
                                                d["locations"][0].update(description=GURMUKHI_SENTENCE))))
    assert "decision 1 reason: write this in English" in text
    assert "garments: write this in English" in text and "description: write this in English" in text


def test_a_few_native_terms_inside_english_are_fine():
    p = ready_project()
    ok = "cotton kurta with a phulkari (ਫੁਲਕਾਰੀ) dupatta (ਦੁਪੱਟਾ) over the head"
    assert problems_for(p, lambda d: d["costumes"][0].update(garments=ok)) == []


def test_mixed_script_words_are_caught():
    p = ready_project()
    text = " ".join(problems_for(p, lambda d: d["locations"][0].update(description="fields of ਗandum around the house")))
    assert "mixes scripts inside a word" in text and "ਗandum" in text


@pytest.mark.parametrize("field,value", [
    ("name_roman", "Harbans (Postman)"),
    ("name_native", "ਹਰੀ (ਪਿੰਡ ਦੇ ਬਜ਼ੁਰਗ, ਰਿਟਾਇਰ ਅਧਿਆਪਕ)"),
    ("name_roman", "A very long descriptive name here"),
])
def test_names_must_be_just_names(field, value):
    p = ready_project()
    assert any("must be just a name" in m for m in problems_for(p, lambda d: d["characters"][0].update({field: value})))


def test_story_world_decisions_are_always_flagged_for_the_reviewer():
    p = ready_project()
    build_plan(p, happy(p, decisions=[dec("PROP_LETTER", dim="story_world", basis="pack", facts=["F014"]),
                                      dec("CHAR_RAVI", dim="verbal")]))
    story, verbal = p.decisions
    assert story.uncertain and "story events" in story.uncertain_reason
    assert not verbal.uncertain


# ---- fixes from the second live run ---------------------------------------------------------------
@pytest.mark.parametrize("word", ["paṛh", "kivẽ", "tusī̃", "ṭhīk", "Maa"])
def test_romanised_punjabi_with_diacritics_is_not_a_script_mix(word):
    p = ready_project()
    assert problems_for(p, lambda d: d["decisions"][0].update(adapted=f"Ravi says {word} to her")) == []


def test_a_scene_decision_may_be_about_a_character_who_is_not_in_the_scene():
    p = ready_project()
    llm = FakeLLM([entity_json(p)] + [scene_json(s, [dec("CHAR_UNCLE_HARI")] if s == "SC04" else []) for s in SCENES])
    build_plan(p, llm)
    assert p.plan.problems == []  # Uncle Hari is not in SC04 but is mentioned there


def test_the_plan_must_fix_one_season_and_scene_prompts_carry_it():
    p = ready_project()
    assert any("season_and_period" in m for m in problems_for(p, lambda d: d.update(season_and_period="")))
    llm = happy(p, mutate=lambda d: d.update(season_and_period="humid monsoon, 1990s"))
    build_plan(p, llm)
    assert all("humid monsoon, 1990s" in c["prompt"] for c in llm.calls[1:])  # every scene call sees the same world
