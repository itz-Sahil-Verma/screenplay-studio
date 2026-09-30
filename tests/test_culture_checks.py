"""The cultural checks: data from the pack, decisions by code, the final word with a person."""
import json

from app.culture_packs.loader import load_pack, load_scripts
from app.models import AdaptationDecision
from app.pipeline.culture_checks import has_term, markers_in, name_kept, tokens
from app.pipeline.plan import verify_entity_plan
from app.models.plan import EntityPlan
from tests.test_plan import entity_json, ready_project

PACK = load_pack("majhi_punjabi")
SCRIPT = load_scripts()["gurmukhi"]


def plan_with(p, **changes):
    data = json.loads(entity_json(p))
    for cid, fields in changes.items():
        entry = next(c for c in data["characters"] if c["character_id"] == cid)
        entry.update(fields)
    return EntityPlan.model_validate(data)


def test_tokens_keep_gurmukhi_words_whole():
    assert tokens("ਪਾਪਾ ਜੀ, ਫ੍ਰਾਇਡੇ ਤੱਕ!") == ["ਪਾਪਾ", "ਜੀ", "ਫ੍ਰਾਇਡੇ", "ਤੱਕ"]
    assert has_term("Singh Tools & Ironmongers", "singh") and not has_term("Singhania Traders", "Singh")


def test_a_name_left_as_in_the_source_is_caught():
    assert name_kept("Samir", "Samar") and name_kept("Ravi", "Ravi") and not name_kept("Desai", "Harjit")


def test_the_plan_must_adapt_a_kept_name_or_justify_it():
    p = ready_project()
    src = p.character("CHAR_RAVI").name
    problems = verify_entity_plan(p, PACK, SCRIPT, plan_with(p, CHAR_RAVI={"name_roman": src}))
    assert any("CHAR_RAVI: name" in m and "nearly" in m for m in problems)


def test_an_uncertain_decision_about_the_character_justifies_keeping_the_name():
    p = ready_project()
    plan = plan_with(p, CHAR_RAVI={"name_roman": p.character("CHAR_RAVI").name})
    plan.decisions.append(plan.decisions[0].model_copy(update={"entity_id": "CHAR_RAVI", "uncertain": True}))
    assert not any("CHAR_RAVI: name" in m for m in verify_entity_plan(p, PACK, SCRIPT, plan))


def test_a_community_marker_the_source_does_not_use_is_caught():
    p = ready_project()
    problems = verify_entity_plan(p, PACK, SCRIPT, plan_with(p, CHAR_RAVI={"name_roman": "Gurpreet Singh"}))
    assert any("'Singh' asserts Sikh religious identity" in m for m in problems)


def test_a_marker_the_source_itself_uses_is_allowed():
    p = ready_project()
    p.source_text += "\nRAVI SINGH walks in."
    assert markers_in("Gurpreet Singh", PACK, p.source_text) == []


def test_a_persons_own_edit_is_not_second_guessed():
    p = ready_project()
    p.user_edits.append("edited plan character CHAR_RAVI: ['name_roman']")
    problems = verify_entity_plan(p, PACK, SCRIPT, plan_with(p, CHAR_RAVI={"name_roman": "Gurpreet Singh"}))
    assert not any(m.startswith("CHAR_RAVI") and "asserts" in m for m in problems)


def test_a_decision_using_a_marker_is_flagged_for_review():
    from tests.test_review import get_ready_to_approve
    from app.pipeline.plan import flatten_decisions
    p = get_ready_to_approve()
    d = p.plan.entities.decisions[0]
    p.plan.entities.decisions[0] = d.model_copy(update={"adapted": "the shop becomes Singh Hardware", "uncertain": False})
    out = flatten_decisions(p, PACK)
    first = next(x for x in out if x.adapted == "the shop becomes Singh Hardware")
    assert isinstance(first, AdaptationDecision) and first.uncertain and "'Singh'" in first.uncertain_reason


def test_the_rewrite_rejects_english_spelled_out_in_gurmukhi():
    from tests.test_rewrite import approved_project, rewrite_json
    from app.pipeline.rewrite import SceneRewrite, verify_rewrite
    p = approved_project()
    sr = SceneRewrite.model_validate_json(rewrite_json(p, "SC01"))
    sr.lines[0].text = "ਫ੍ਰਾਇਡੇ ਤੱਕ ਜਵਾਬ ਦਿਓ।"
    problems = verify_rewrite(p, SCRIPT, p.scene("SC01"), sr, PACK)
    assert any("ਫ੍ਰਾਇਡੇ" in m and "ਸ਼ੁੱਕਰਵਾਰ" in m for m in problems)


def test_the_lists_are_pack_data_and_say_they_are_unreviewed():
    assert PACK.identity_markers and PACK.avoid_terms and "NOT reviewed" in PACK.lists_note
    assert "identity markers" in PACK.for_prompt()  # the model is told up front, not only corrected afterwards
