from pathlib import Path

from evals.score import format_report, load_gold, score_continuity, score_extraction, score_plan
from tests.test_plan import ready_project

GOLD = load_gold(Path(__file__).parent.parent / "evals" / "gold_letter.json")


def test_the_gold_labels_match_the_known_good_sample_run():
    """The reference run (a real Azure extraction, normalized and checked in code) must score perfectly against its own gold."""
    p = ready_project()
    e = score_extraction(p, GOLD)
    assert e["characters"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "duplicates": {}, "unexpected": []}
    assert e["scenes"]["ok"] and e["dialogue_lines_per_scene"]["ok"] and all(e["props_found"].values())
    assert e["costumes"]["Ravi"]["count"] == 2 and len(e["costumes"]["Ravi"]["found"]) == 2
    c = score_continuity(p, GOLD)
    assert c["recall"] == "3/3" and c["missed"] == [] and c["injury_tracked"] == {"Ravi": True}


def test_a_duplicate_character_and_a_hallucinated_one_are_penalised():
    from app.models import Character
    p = ready_project()
    p.characters.append(Character(id="CHAR_RAVI_2", name="Ravi"))      # the same person twice
    p.characters.append(Character(id="CHAR_GHOST", name="Ghost"))      # not in the story
    e = score_extraction(p, GOLD)["characters"]
    assert e["duplicates"] == {"Ravi": ["CHAR_RAVI", "CHAR_RAVI_2"]} and e["unexpected"] == ["Ghost"]
    assert e["precision"] < 1.0 and e["recall"] == 1.0


def test_a_missed_trap_is_reported_by_name():
    p = ready_project()
    p.warnings = [w for w in p.warnings if w.code != "COSTUME_CHANGE_NO_REASON"]
    c = score_continuity(p, GOLD)
    assert c["recall"] == "2/3" and "Ravi's blue jacket becomes a red shirt with no reason" in c["missed"]


def test_the_report_is_readable():
    p = ready_project()
    text = format_report("t", score_extraction(p, GOLD), score_continuity(p, GOLD), score_plan(p) if p.plan else None)
    assert "characters P/R/F1: 1.0/1.0/1.0" in text and "continuity traps caught: 3/3" in text
