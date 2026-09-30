"""Scores a pipeline run against hand-written gold labels.

Why this exists: a change that makes the pipeline faster must not quietly make it worse. These numbers turn
"it looks fine" into evidence, and they are the same numbers whether the run was live or replayed from a cache.
Everything here is deterministic; only the pipeline output being scored comes from a model.
"""
import json
import re
from pathlib import Path

from app.models import Project
from app.pipeline.normalize import norm_key
from app.pipeline.rewrite import source_dialogue, verify_rewrite
from app.culture_packs.loader import load_scripts


def load_gold(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _prf(predicted: int, matched_pred: int, gold: int, matched_gold: int) -> dict:
    p = matched_pred / predicted if predicted else 0.0
    r = matched_gold / gold if gold else 0.0
    return {"precision": round(p, 2), "recall": round(r, 2), "f1": round(2 * p * r / (p + r), 2) if p + r else 0.0}


def score_extraction(p: Project, gold: dict) -> dict:
    names_of = {c.id: {norm_key(c.name), *(norm_key(a) for a in c.aliases)} for c in p.characters}
    gold_keys = {norm_key(g): g for g in gold["characters"]}
    matched: dict[str, list[str]] = {}  # gold name -> predicted character ids that map to it
    for cid, names in names_of.items():
        for gk, g in gold_keys.items():
            if gk in names or any(gk in n.split() for n in names):  # "Desai" is "Mr. Desai"
                matched.setdefault(g, []).append(cid)
    duplicates = {g: ids for g, ids in matched.items() if len(ids) > 1}
    extra = [c.name for c in p.characters if not any(c.id in ids for ids in matched.values())]
    prop_words = " ".join(x.name.lower() for x in p.props)
    dialogue = [len(source_dialogue(p, s)) for s in sorted(p.scenes, key=lambda s: s.number)]
    costumes = {}
    for who, wanted in gold.get("costumes", {}).items():
        cid = next((c.id for c in p.characters if norm_key(who) in {norm_key(c.name), *map(norm_key, c.aliases)}), None)
        have = " | ".join((k.source_garments or k.garments).lower() for k in p.costumes if k.character_id == cid)
        costumes[who] = {"expected": wanted, "found": [w for w in wanted if w in have], "count": sum(k.character_id == cid for k in p.costumes)}
    return {
        "scenes": {"expected": gold["scenes"], "found": len(p.scenes), "ok": len(p.scenes) == gold["scenes"]},
        "characters": {**_prf(len(p.characters), len(p.characters) - len(extra), len(gold_keys), len(matched)),
                       "duplicates": duplicates, "unexpected": extra},
        "props_found": {w: (w in prop_words) for w in gold.get("props_must_include", [])},
        "costumes": costumes,
        "dialogue_lines_per_scene": {"expected": gold["dialogue_lines_per_scene"], "found": dialogue, "ok": dialogue == gold["dialogue_lines_per_scene"]},
    }


def score_continuity(p: Project, gold: dict) -> dict:
    caught, missed = [], []
    for exp in gold["expected_findings"]:
        hit = any(w.code in exp["any_code"] and exp["entity_contains"] in ((w.entity_id or "") + " " + w.message).lower() for w in p.warnings)
        (caught if hit else missed).append(exp["what"])
    expected_codes = {c for e in gold["expected_findings"] for c in e["any_code"]}
    extra = [(w.severity.value, w.code, w.entity_id) for w in p.warnings if w.code not in expected_codes and w.severity.value != "info"]
    injuries = {}
    for who, word in gold.get("injuries", {}).items():
        injuries[who] = any(word in i.lower() for s in p.scenes for st in s.states.values() for i in st.injuries)
    return {"recall": f"{len(caught)}/{len(gold['expected_findings'])}", "caught": caught, "missed": missed,
            "other_findings_to_review": extra, "injury_tracked": injuries}


def score_plan(p: Project) -> dict:
    d = p.decisions
    return {"status": p.status.value, "problems": p.plan.problems if p.plan else None, "failed_scenes": p.plan.failed_scenes if p.plan else None,
            "decisions": len(d), "flagged": sum(x.uncertain for x in d), "pack_backed": sum(x.basis == "pack" for x in d),
            "unlinked": sum(x.entity_id is None for x in d)}


def score_rewrite(p: Project) -> dict:
    """Recomputed from scratch with the same verifier the pipeline uses: structure, order, script purity, coverage."""
    script = load_scripts()[p.selection.output_script]
    scenes = {}
    for a in p.adapted_scenes:
        scene = next(s for s in p.scenes if s.scene_id == a.source_scene_id)
        from app.pipeline.rewrite import SceneRewrite, LineDraft
        sr = SceneRewrite(scene_id=a.source_scene_id, heading=a.heading, lines=[
            LineDraft(kind=l.kind.value, character_id=l.character_id or "", text=l.text, gloss=l.gloss, source_line=l.source_line or 0,
                      event_ids=l.event_ids, decision_ids=l.decision_ids, uncertain=l.uncertain, note=l.note) for l in a.lines])
        scenes[a.source_scene_id] = {"lines": len(a.lines), "uncertain": sum(l.uncertain for l in a.lines),
                                     "problems": verify_rewrite(p, script, scene, sr)}
    return {"status": p.status.value, "failed": p.rewrite_failed, "scenes": scenes,
            "all_scenes_clean": bool(scenes) and all(not v["problems"] for v in scenes.values())}


def format_report(name: str, extraction: dict, continuity: dict, plan: dict | None = None, rewrite: dict | None = None, timing: dict | None = None) -> str:
    L = [f"=== EVAL: {name} ==="]
    e = extraction
    L.append(f"scenes: {e['scenes']['found']}/{e['scenes']['expected']} | characters P/R/F1: {e['characters']['precision']}/{e['characters']['recall']}/{e['characters']['f1']}"
             f" | duplicates: {e['characters']['duplicates'] or 'none'} | unexpected: {e['characters']['unexpected'] or 'none'}")
    L.append(f"props found: {e['props_found']} | costumes: " + "; ".join(f"{k}: {len(v['found'])}/{len(v['expected'])} looks, {v['count']} records" for k, v in e['costumes'].items()))
    L.append(f"dialogue lines per scene: found {e['dialogue_lines_per_scene']['found']} vs expected {e['dialogue_lines_per_scene']['expected']} -> {'ok' if e['dialogue_lines_per_scene']['ok'] else 'MISMATCH'}")
    c = continuity
    L.append(f"continuity traps caught: {c['recall']} | missed: {c['missed'] or 'none'} | injuries tracked: {c['injury_tracked']}")
    L.append(f"other findings for a human to review: {c['other_findings_to_review'] or 'none'}")
    if plan:
        L.append(f"plan: {plan['status']} | decisions {plan['decisions']} (flagged {plan['flagged']}, pack-backed {plan['pack_backed']}, unlinked {plan['unlinked']}) | problems: {plan['problems'] or 'none'}")
    if rewrite:
        L.append(f"rewrite: {rewrite['status']} | every scene passes the verifier: {rewrite['all_scenes_clean']} | " + "; ".join(f"{sid}: {v['lines']} lines, {len(v['problems'])} problems" for sid, v in rewrite['scenes'].items()))
    if timing:
        L.append("cost/latency: " + json.dumps(timing))
    return "\n".join(L)
