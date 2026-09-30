"""Step 8: the cultural adaptation plan.

Two kinds of model calls:
  * ONE entity call: names, roles, appearance, costumes, locations, props for the whole cast, so
    every scene later uses the same names and looks.
  * ONE call per scene: dialogue register, gestures, food, sound, rituals for that scene, given
    the entity plan. A single scene can be re-planned without touching the others.

The model proposes; code verifies (coverage of every source ID, no invented IDs or fact IDs,
native names really in the chosen script, distinct costumes stay distinct) and owns the
bookkeeping (decision IDs, source scenes, uncertainty). Only the project's own culture pack is
ever put in a prompt, so nothing leaks between cultures. Nothing is applied to the canonical
records until the user approves (Step 9).
"""
import json
import logging
import unicodedata

from app.config import settings
from app.culture_packs.loader import load_pack, load_scripts
from app.llm.base import LLMClient, LLMError, try_parse
from app.models import (
    AdaptationDecision,
    AdaptationPlan,
    Approval,
    CulturePack,
    Dimension,
    EntityPlan,
    Project,
    ProjectStatus,
    ScenePlan,
    ScriptInfo,
    Severity,
)
from app.models.plan import DecisionDraft
from app.pipeline.extract import client_id
from app.pipeline.culture_checks import human_edited, markers_in, name_kept
from app.pipeline.normalize import norm_key
from app.pipeline.parallel import run_parallel
from app.storage import JsonCache, default_cache, make_key

log = logging.getLogger(__name__)

DIMENSIONS = {d.value for d in Dimension}

RULES_COMMON = """- PRESERVE THE STORY: keep every character relationship, each scene's dramatic purpose and the emotional arc. A cultural change must never create a plot hole or reverse a motivation.
- Use the culture pack's facts wherever they apply and cite their ids in fact_ids (basis "pack"). If you go beyond the pack, use basis "judgment". Set uncertain=true whenever you are not sure it is right for this culture.
- Follow the pack's RULEs. Do not assume a religion from the region or dialect. Do not import objects, clothing, food or words from other regions or dialects.
- Every decision needs original, adapted and a reason a reviewer can check. Record only the choices a reader would notice most, most important FIRST, and keep every text field short (under about 30 words). Budget: at most 12 decisions for the cast plan and at most 5 per scene; anything beyond the budget is discarded.
- LANGUAGE: write every description, reason and note in plain ENGLISH so a reviewer who does not read the output script can check it. Native-script text belongs only in the *_native fields and as short quoted terms in parentheses. Never mix two scripts inside one word.
- Output valid JSON for the given schema and nothing else."""

ENTITY_SYSTEM = f"""You are a cultural adaptation writer and production designer. You re-create a screenplay's world inside ONE specific culture, described in the CULTURE PACK you are given.

Rules:
- Give exactly ONE entry for EVERY id listed under REQUIRED IDS, spelling the ids exactly. Never invent an id.
- Names: give name_roman (Latin letters) and name_native (written in the OUTPUT SCRIPT). A name is ONLY the name (1-3 words): no job, no description, nothing in brackets. A name is a creative choice: pick names natural to the region, community, class and age of the character. Every character name must be different.
- Costumes: keep every source costume as its own costume; never merge two or make two identical. Describe garments, fabrics, colours, footwear, jewellery, headwear and grooming specifically for the region and the rural/urban setting. If a character changes costume between scenes and the source gives no reason, propose a small believable change_reason and record it as a story_world decision, because it adds story detail.
- season_and_period: fix ONE season / time of year and era for the whole story. The source may not say: choose what fits the region and the scenes' weather and times of day, and record it as a visual_world decision. Every scene will be planned separately and must agree with it (clothing weight, light, food, sound).
- Characters need an appearance (build, face, apparent age) and grooming that fit the culture, age and role.
{RULES_COMMON}"""

SCENE_SYSTEM = f"""You are a cultural adaptation writer. You adapt ONE scene of a screenplay for ONE specific culture, described in the CULTURE PACK. The names, looks and places of the whole cast are already decided (ENTITY PLAN): use them exactly.

Stay consistent with the WORLD notes (season and era) for the whole story: do not contradict them in weather, clothing, light, food or sound.

Produce for this scene:
- setting_notes: time, light, weather and atmosphere as they would really be in this region.
- dialogue_notes: how the speech must differ from a literal translation: register, the respectful vs intimate 'you', kinship terms used instead of names, politeness, humour, rhythm, code-switching.
- gestures: non-verbal behaviour: greeting, touch, posture, eye contact, silence, seating, eating, personal space.
- food, sound_music, rituals: only what belongs to this region, season and time.
{RULES_COMMON}"""


# ---- prompts ------------------------------------------------------------------------------
def _selection_text(project: Project, pack: CulturePack, scripts: dict[str, ScriptInfo]) -> str:
    s = project.selection
    return (f"Region: {s.region}. Setting: {s.setting.value}. "
            f"OUTPUT SCRIPT: {scripts[s.output_script].label} (write every *_native field in this script).")


def entity_prompt(project: Project, pack: CulturePack, scripts: dict[str, ScriptInfo]) -> str:
    chars = [{"id": c.id, "name": c.name, "aliases": c.aliases, "age": c.age, "role": c.role,
              "personality": c.personality, "relationships": c.relationship_notes, "scenes": c.scene_ids}
             for c in project.characters]
    costumes = [{"id": c.id, "character": c.character_id, "source_garments": c.garments,
                 "scenes": c.scene_ids, "source_change_reason": c.change_reason} for c in project.costumes]
    locs = [{"id": l.id, "name": l.name, "sub_locations": l.sub_locations, "scenes": l.scene_ids}
            for l in project.locations]
    props = [{"id": p.id, "name": p.name, "description": p.description, "scenes": p.scene_ids}
             for p in project.props]
    scenes = [{"id": s.scene_id, "location": s.location_id, "time": s.time, "summary": s.summary,
               "dramatic_purpose": s.dramatic_purpose, "emotional_change": s.emotional_change}
              for s in project.scenes]
    issues = [w.message for w in project.warnings if w.severity != Severity.INFO]
    required = {"characters": [c["id"] for c in chars], "costumes": [c["id"] for c in costumes],
                "locations": [l["id"] for l in locs], "props": [p["id"] for p in props]}
    dump = lambda o: json.dumps(o, ensure_ascii=False, indent=1)
    return "\n".join([
        "=== CULTURE PACK ===", pack.for_prompt(), "",
        "=== TARGET ===", _selection_text(project, pack, scripts), "",
        "=== SOURCE CHARACTERS ===", dump(chars), "=== SOURCE COSTUMES ===", dump(costumes),
        "=== SOURCE LOCATIONS ===", dump(locs), "=== SOURCE PROPS ===", dump(props),
        "=== SOURCE SCENES ===", dump(scenes),
        "=== CONTINUITY ISSUES FOUND IN THE SOURCE (do not make these worse) ===", dump(issues), "",
        "=== REQUIRED IDS (one entry each) ===", dump(required),
    ])


def scene_prompt(project: Project, pack: CulturePack, scripts: dict[str, ScriptInfo], scene_id: str) -> str:
    scene = next(s for s in project.scenes if s.scene_id == scene_id)
    ent = project.plan.entities
    name = {c.character_id: f"{c.name_roman} ({c.name_native})" for c in ent.characters}
    garment = {c.costume_id: c.garments for c in ent.costumes}
    entity_summary = {
        "characters": [c.model_dump() for c in ent.characters],
        "locations": [l.model_dump() for l in ent.locations],
        "props": [p.model_dump() for p in ent.props],
    }
    record = {
        "scene_id": scene.scene_id, "location": scene.location_id, "time": scene.time,
        "characters": [{"id": c, "adapted_name": name.get(c, c),
                        "costume": garment.get(scene.costumes.get(c, ""), "")} for c in scene.characters],
        "prop_holders_at_start": scene.prop_holder_start, "prop_holders_at_end": scene.prop_holder_end,
        "events": [{"kind": e.kind.value, "character": e.character_id, "item": e.item,
                    "to": e.to_character_id} for e in scene.state_changes],
    }
    dump = lambda o: json.dumps(o, ensure_ascii=False, indent=1)
    return "\n".join([
        "=== CULTURE PACK ===", pack.for_prompt(), "",
        "=== TARGET ===", _selection_text(project, pack, scripts), "",
        "=== WORLD (the same for every scene) ===", ent.season_and_period, "",
        "=== ENTITY PLAN (already decided) ===", dump(entity_summary), "",
        "=== SCENE RECORD ===", dump(record), "",
        "=== SCENE SOURCE TEXT ===", scene.source_text, "=== END ===",
        f"Set scene_id to {scene_id!r}.",
    ])


# ---- verification (code) --------------------------------------------------------------------
def _script_problem(text: str, script: ScriptInfo, where: str) -> str | None:
    if not text.strip():
        return f"{where}: empty"
    bad = sorted({ch for ch in text if ch.isalpha() and not script.contains(ch)})
    if bad:
        return f"{where}: {text!r} contains letters outside {script.label} ({''.join(bad[:6])})"
    return None


def _is_latin(ch: str) -> bool:
    """Latin script including transliteration letters like ṛ, ẽ, ṉ."""
    return unicodedata.name(ch, "").startswith("LATIN")


def _english_problem(text: str, where: str, max_native: float = 0.3) -> str | None:
    """Descriptive text must be readable English; native terms are allowed only in small amounts."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(not _is_latin(c) for c in letters) / len(letters) > max_native:
        return f"{where}: write this in English (native-script terms only as short quoted terms)"
    return None


def _mixed_script_words(text: str) -> list[str]:
    import re
    out = []
    for tok in re.split(r"[\s,;:()\"'\u201c\u201d\u2018\u2019/\-\u2013\u2014.!?]+", text):
        letters = [c for c in tok if c.isalpha()]
        if any(_is_latin(c) for c in letters) and any(not _is_latin(c) for c in letters):
            out.append(tok)
    return out


def _malformed_words(text: str) -> list[str]:
    """Words that begin with a dependent mark (a vowel sign or virama with no letter to attach to): broken orthography."""
    import re
    out = []
    for tok in re.split(r"[\s,;:()\"'\u201c\u201d\u2018\u2019/\-\u2013\u2014.!?\u2026]+", text):
        if tok and unicodedata.category(tok[0]) in ("Mn", "Mc"):
            out.append(tok)
    return out


def _text_problems(text: str, where: str, english: bool = True) -> list[str]:
    out = []
    if english:
        msg = _english_problem(text, where)
        if msg:
            out.append(msg)
    bad = _mixed_script_words(text)
    if bad:
        out.append(f"{where}: mixes scripts inside a word: {bad[:3]}")
    broken = _malformed_words(text)
    if broken:
        out.append(f"{where}: malformed word(s) that start with a vowel sign: {broken[:3]}")
    return out


def _name_problem(name: str, where: str) -> str | None:
    if len(name.split()) > 4 or any(ch in name for ch in "(),;:"):
        return f"{where}: {name!r} must be just a name (1-3 words, no brackets or descriptions)"
    return None


def _coverage(kind: str, required: list[str], got: list[str], problems: list[str]) -> None:
    dupes = sorted({i for i in got if got.count(i) > 1})
    missing = sorted(set(required) - set(got))
    unknown = sorted(set(got) - set(required))
    if missing:
        problems.append(f"{kind}: missing entries for {missing}")
    if unknown:
        problems.append(f"{kind}: unknown ids {unknown} (only use the REQUIRED IDS)")
    if dupes:
        problems.append(f"{kind}: more than one entry for {dupes}")


def _check_decisions(decisions: list[DecisionDraft], pack: CulturePack, where: str, problems: list[str]) -> None:
    """Checks what matters. An unknown `entity_id` is deliberately NOT a problem: it is only a link label,
    and flatten_decisions() simply leaves such a decision unlinked instead of failing the whole plan."""
    fact_ids = {f.id for f in pack.facts}
    for i, d in enumerate(decisions, 1):
        tag = f"{where} decision {i}"
        for field in ("original", "adapted", "reason"):
            problems += _text_problems(getattr(d, field), f"{tag} {field}")
        if d.dimension not in DIMENSIONS:
            problems.append(f"{tag}: unknown dimension {d.dimension!r}")
        for field in ("original", "adapted", "reason"):
            if not getattr(d, field).strip():
                problems.append(f"{tag}: empty {field}")
        bad = [f for f in d.fact_ids if f not in fact_ids]
        if bad:
            problems.append(f"{tag}: cites facts that are not in the pack: {bad}")
        if d.basis == "pack" and not d.fact_ids:
            problems.append(f"{tag}: basis is 'pack' but no fact_ids are cited (use basis 'judgment')")


def _registry_ids(project: Project) -> set[str]:
    return ({c.id for c in project.characters} | {c.id for c in project.costumes}
            | {l.id for l in project.locations} | {p.id for p in project.props}
            | {s.scene_id for s in project.scenes})


def _culture_problems(project: Project, pack: CulturePack, plan: EntityPlan) -> list[str]:
    """Names that were not adapted, and identity markers the source does not establish. Either is fine when a
    decision about that entity is marked uncertain (a person must then review it) or a person made the edit."""
    source = project.source_text
    ok = human_edited(project) | {d.entity_id for d in plan.decisions if d.uncertain and d.entity_id}
    how = ("adapt it, or add a decision (entity_id {id}) with uncertain=true saying why it fits "
           f"{pack.culture}")
    out: list[str] = []
    for c in plan.characters:
        src = project.character(c.character_id)
        if c.character_id in ok or src is None:
            continue
        if name_kept(src.name, c.name_roman):
            out.append(f"{c.character_id}: name {c.name_roman!r} is (nearly) the source name {src.name!r}: "
                       + how.format(id=c.character_id))
        for label, txt in (("name", c.name_roman), ("role_adapted", c.role_adapted)):
            for m in markers_in(txt, pack, source):
                out.append(f"{c.character_id} {label}: {m!r} asserts {_marks(pack, m)}, which the source does not establish: "
                           + how.format(id=c.character_id))
    named = [(l.location_id, l.name_roman, l.description) for l in plan.locations] + \
            [(x.prop_id, x.name_roman, x.description) for x in plan.props]
    for eid, name, desc in named:
        if eid in ok:
            continue
        for m in markers_in(f"{name} {desc}", pack, source):
            out.append(f"{eid}: {m!r} asserts {_marks(pack, m)}, which the source does not establish: " + how.format(id=eid))
    return out


def _marks(pack: CulturePack, term: str) -> str:
    return next((m.marks for m in pack.identity_markers if m.term == term), "an identity")


def verify_entity_plan(project: Project, pack: CulturePack, script: ScriptInfo, plan: EntityPlan) -> list[str]:
    problems: list[str] = []
    if not plan.season_and_period.strip():
        problems.append("season_and_period is empty: fix one season and era for the whole story")
    problems += _text_problems(plan.season_and_period, "season_and_period")
    _coverage("characters", [c.id for c in project.characters], [c.character_id for c in plan.characters], problems)
    _coverage("costumes", [c.id for c in project.costumes], [c.costume_id for c in plan.costumes], problems)
    _coverage("locations", [l.id for l in project.locations], [l.location_id for l in plan.locations], problems)
    _coverage("props", [p.id for p in project.props], [p.prop_id for p in plan.props], problems)

    names: dict[str, str] = {}
    for c in plan.characters:
        msg = _script_problem(c.name_native, script, f"{c.character_id} name_native")
        if msg:
            problems.append(msg)
        if not c.name_roman.strip():
            problems.append(f"{c.character_id}: empty name_roman")
        for nm, label in ((c.name_roman, "name_roman"), (c.name_native, "name_native")):
            msg = _name_problem(nm, f"{c.character_id} {label}")
            if msg:
                problems.append(msg)
        for label, txt in (("role_adapted", c.role_adapted), ("speech_register", c.speech_register),
                           ("appearance", c.appearance), ("grooming", c.grooming)):
            problems += _text_problems(txt, f"{c.character_id} {label}")
        if not c.appearance.strip():
            problems.append(f"{c.character_id}: empty appearance (needed for the character bible)")
        for key in (norm_key(c.name_roman), c.name_native.strip()):
            if key and key in names and names[key] != c.character_id:
                problems.append(f"{c.character_id} and {names[key]} have the same name {key!r}")
            names[key] = c.character_id
    for p in plan.props:
        msg = _script_problem(p.name_native, script, f"{p.prop_id} name_native")
        if msg:
            problems.append(msg)
        msg = _name_problem(p.name_native, f"{p.prop_id} name_native")
        if msg:
            problems.append(msg)
        problems += _text_problems(p.description, f"{p.prop_id} description")
    for l in plan.locations:
        if l.name_native.strip():
            msg = _script_problem(l.name_native, script, f"{l.location_id} name_native")
            if msg:
                problems.append(msg)
        if not l.description.strip():
            problems.append(f"{l.location_id}: empty description")
        problems += _text_problems(l.description, f"{l.location_id} description")

    look: dict[tuple[str, str], str] = {}
    owner = {c.id: c.character_id for c in project.costumes}
    for c in plan.costumes:
        if not c.garments.strip():
            problems.append(f"{c.costume_id}: empty garments")
        for label in ("garments", "fabrics", "colours", "footwear", "jewellery", "headwear", "grooming", "change_reason"):
            problems += _text_problems(getattr(c, label), f"{c.costume_id} {label}")
        key = (owner.get(c.costume_id, "?"), norm_key(c.garments) + "|" + norm_key(c.colours))
        if key in look and look[key] != c.costume_id:
            problems.append(f"costumes {look[key]} and {c.costume_id} are identical: distinct costumes must look different")
        look[key] = c.costume_id

    _check_decisions(plan.decisions, pack, "entity plan", problems)
    problems += _culture_problems(project, pack, plan)
    return problems


def verify_scene_plan(project: Project, pack: CulturePack, scene_id: str, plan: ScenePlan) -> list[str]:
    problems: list[str] = []
    if plan.scene_id != scene_id:
        problems.append(f"scene_id is {plan.scene_id!r}, expected {scene_id!r}")
    if not plan.dialogue_notes.strip():
        problems.append("dialogue_notes is empty (say how speech differs from a literal translation)")
    if not plan.gestures:
        problems.append("no gestures given")
    for label in ("setting_notes", "dialogue_notes"):
        problems += _text_problems(getattr(plan, label), f"{scene_id} {label}")
    for label in ("gestures", "food", "sound_music", "rituals"):
        for item in getattr(plan, label):
            problems += _text_problems(item, f"{scene_id} {label}")
    _check_decisions(plan.decisions, pack, scene_id, problems)
    return problems


def all_problems(project: Project, pack: CulturePack, script: ScriptInfo) -> list[str]:
    """Re-verified from current state every time, so it can never go stale."""
    plan = project.plan
    out: list[str] = []
    if plan.entities is not None:
        out += verify_entity_plan(project, pack, script, plan.entities)
    for sid, sp in plan.scenes.items():
        out += [f"{sid}: {m}" for m in verify_scene_plan(project, pack, sid, sp)]
    out += [f"{sid}: planning failed: {err}" for sid, err in plan.failed_scenes.items()]
    return out


# ---- the model loop (one call budget per piece) -----------------------------------------------
def _ask(client: LLMClient, cache: JsonCache, system: str, prompt: str, schema, verify,
         fresh: bool = False, repair=None) -> tuple[object, list[str]]:
    """Returns (best parsed answer, unresolved problems). Raises LLMError if nothing parseable came back.
    `fresh` skips the cache READ (an explicit "regenerate"); a verified result is still written.
    `repair(obj)` fixes what CODE can fix (e.g. enforcing output budgets) before verification, because a
    deterministic repair costs nothing and a model retry costs a whole call."""
    key = make_key(system, prompt, client_id(client))
    hit = None if fresh else cache.get(key)
    if hit is not None:
        return schema.model_validate(hit), []
    feedback: list[str] = []
    best, best_problems = None, []
    calls = 0
    while calls < settings.llm_max_retries:
        calls += 1
        p = prompt
        if feedback:
            p += "\n\nYour previous answer had these problems, fix ALL of them:\n- " + "\n- ".join(feedback)
        obj, err = try_parse(client.complete_json(system, p, schema), schema)
        if obj is None:
            feedback = [f"the JSON did not match the schema: {err}"]
            continue
        if repair:
            repair(obj)
        best, best_problems = obj, verify(obj)
        if not best_problems:
            cache.set(key, best.model_dump(mode="json"))  # only verified answers are cached
            return best, []
        feedback = best_problems
    if best is None:
        raise LLMError(f"no valid output after {calls} model calls: {feedback[0]}")
    return best, best_problems


# Output budgets. A call takes about as long as the text it writes (measured: ~85 output tokens/s), so the amount of
# text is capped in code: whatever the model returns beyond these limits is dropped (it was told to put the most
# important items first). This also keeps the human review load bounded.
MAX_ENTITY_DECISIONS = 14
MAX_SCENE_DECISIONS = 6
MAX_LIST_ITEMS = 6


def cap_entity_plan(plan: EntityPlan) -> None:
    plan.decisions = plan.decisions[:MAX_ENTITY_DECISIONS]


def cap_scene_plan(plan: ScenePlan) -> None:
    plan.decisions = plan.decisions[:MAX_SCENE_DECISIONS]
    for name in ("gestures", "food", "sound_music", "rituals"):
        setattr(plan, name, getattr(plan, name)[:MAX_LIST_ITEMS])


def plan_entities(project: Project, client: LLMClient, pack: CulturePack, scripts, cache: JsonCache,
                  fresh: bool = False) -> None:
    script = scripts[project.selection.output_script]
    plan, _ = _ask(client, cache, ENTITY_SYSTEM, entity_prompt(project, pack, scripts), EntityPlan,
                   lambda p: verify_entity_plan(project, pack, script, p), fresh, repair=cap_entity_plan)
    project.plan.entities = plan
    project.plan.scenes = {}  # scene plans depend on the entity plan's names: they must be redone
    project.plan.failed_scenes = {}
    project.plan.stale_scenes = []


def _plan_scene_call(project: Project, scene_id: str, client: LLMClient, pack: CulturePack, scripts, cache: JsonCache,
                     fresh: bool = False) -> ScenePlan:
    """The model call for one scene. Read-only on the project, so it is safe to run in a worker thread."""
    sp, _ = _ask(client, cache, SCENE_SYSTEM, scene_prompt(project, pack, scripts, scene_id), ScenePlan,
                 lambda p: verify_scene_plan(project, pack, scene_id, p), fresh, repair=cap_scene_plan)
    sp.scene_id = scene_id  # code owns ids
    return sp


def _apply_scene_plan(project: Project, scene_id: str, sp: ScenePlan | None, error: Exception | None) -> None:
    """Record one scene's outcome. Runs on a single thread; a failure here never touches the other scenes."""
    if error is None and sp is not None:
        project.plan.scenes[scene_id] = sp
        project.plan.failed_scenes.pop(scene_id, None)
        if scene_id in project.plan.stale_scenes:
            project.plan.stale_scenes.remove(scene_id)
    else:
        project.plan.scenes.pop(scene_id, None)
        project.plan.failed_scenes[scene_id] = f"{type(error).__name__}: {str(error)[:300]}"
        log.error("scene %s planning failed: %s", scene_id, project.plan.failed_scenes[scene_id])


def plan_scene(project: Project, scene_id: str, client: LLMClient, pack: CulturePack, scripts, cache: JsonCache,
               fresh: bool = False) -> None:
    try:
        sp, err = _plan_scene_call(project, scene_id, client, pack, scripts, cache, fresh), None
    except Exception as e:  # noqa: BLE001: recorded per scene
        sp, err = None, e
    _apply_scene_plan(project, scene_id, sp, err)


# ---- bookkeeping owned by code --------------------------------------------------------------------
def iter_drafts(project: Project) -> list[tuple[DecisionDraft, str | None]]:
    """The plan's decisions in the order that gives them their DEC ids: entity decisions first,
    then each planned scene in story order. Review edits write back through these objects."""
    drafts: list[tuple[DecisionDraft, str | None]] = [(d, None) for d in project.plan.entities.decisions]
    for s in sorted(project.scenes, key=lambda s: s.number):
        if s.scene_id in project.plan.scenes:
            drafts += [(d, s.scene_id) for d in project.plan.scenes[s.scene_id].decisions]
    return drafts


def flatten_decisions(project: Project, pack: CulturePack) -> list[AdaptationDecision]:
    """Turn the plan into reviewable decisions. Code assigns ids, source scenes and uncertainty;
    review state carries over from the previous decisions when a decision is unchanged."""
    flagged = {f.id for f in pack.facts if f.flagged}
    all_scenes = [s.scene_id for s in sorted(project.scenes, key=lambda s: s.number)]
    scenes_of: dict[str, list[str]] = {}
    for coll in (project.characters, project.costumes, project.locations, project.props):
        for r in coll:
            scenes_of[r.id] = r.scene_ids
    previous = {(d.entity_id or "", d.dimension.value, d.original, d.adapted): d for d in project.decisions}
    drafts = iter_drafts(project)
    known = _registry_ids(project)

    out: list[AdaptationDecision] = []
    for n, (d, sid) in enumerate(drafts, 1):
        reasons = []
        if d.uncertain:
            reasons.append("the model marked it uncertain")
        if d.dimension == "story_world":
            reasons.append("changes or adds story events: the reviewer must confirm the story is preserved")
        hit = sorted(set(d.fact_ids) & flagged)
        if hit:
            reasons.append(f"relies on flagged pack fact(s) {', '.join(hit)}")
        marks = markers_in(f"{d.adapted} {d.reason}", pack, project.source_text)
        if marks:
            reasons.append(f"uses {', '.join(repr(m) for m in marks)}, which asserts religion, caste or community the source does not establish")
        eid = d.entity_id if d.entity_id in known else None  # a made-up id leaves the decision unlinked, not rejected
        scenes = [sid] if sid else scenes_of.get(eid or "", all_scenes)
        dec = AdaptationDecision(
            id=f"DEC{n:03d}", dimension=Dimension(d.dimension), source_scene_ids=scenes or all_scenes,
            entity_id=eid, original=d.original, adapted=d.adapted, reason=d.reason,
            basis=d.basis, fact_ids=d.fact_ids, uncertain=bool(reasons), uncertain_reason="; ".join(reasons))
        old = previous.get((eid or "", d.dimension, d.original, d.adapted))
        if old:
            dec.status, dec.reviewer_note = old.status, old.reviewer_note
        out.append(dec)
    return out


def _finish(project: Project, pack: CulturePack, script: ScriptInfo) -> None:
    plan = project.plan
    plan.problems = all_problems(project, pack, script)
    if plan.entities is not None:
        project.decisions = flatten_decisions(project, pack)
    complete = plan.entities is not None and not plan.failed_scenes and all(
        s.scene_id in plan.scenes for s in project.scenes)
    project.approval = Approval()  # anything the user approved before no longer describes this plan
    if complete and project.status == ProjectStatus.NORMALIZED:
        project.transition(ProjectStatus.PLAN_READY)


# ---- public API -----------------------------------------------------------------------------------
def _setup(project: Project, pack: CulturePack | None):
    if project.selection is None:
        raise ValueError("no culture selected: set project.selection first")
    if project.status not in (ProjectStatus.NORMALIZED, ProjectStatus.PLAN_READY):
        raise ValueError(f"planning needs a normalized project, not {project.status.value}")
    if not project.continuity_checked:
        raise ValueError("run the continuity check before planning, so the plan can respect its findings")
    pack = pack or load_pack(project.selection.pack_id)
    scripts = load_scripts()
    project.selection.validate_against(pack, scripts)
    if project.plan is None:
        project.plan = AdaptationPlan()
    return pack, scripts


def build_plan(project: Project, client: LLMClient, pack: CulturePack | None = None,
               cache: JsonCache | None = None, fresh_entities: bool = False, on_progress=None) -> Project:
    """Plan everything that is not planned yet. Re-running only redoes what is missing or failed.

    Two phases with a real dependency between them: the cast plan first (it fixes every name and look), then the
    scene plans, which are independent of each other and run concurrently (LLM_CONCURRENCY)."""
    pack, scripts = _setup(project, pack)
    cache = cache or default_cache("plan")
    project.plan.model = client_id(client)
    missing = [s.scene_id for s in sorted(project.scenes, key=lambda s: s.number) if s.scene_id not in project.plan.scenes]
    need_cast = project.plan.entities is None
    total, done = len(missing) + (1 if need_cast else 0), 0
    if need_cast:
        if on_progress:
            on_progress("Planning the cast, costumes and places", 0, total)
        plan_entities(project, client, pack, scripts, cache, fresh_entities)  # required: raises LLMError if it cannot be produced
        done += 1
        if on_progress:
            on_progress("Planning scenes", done, total)
        missing = [s.scene_id for s in sorted(project.scenes, key=lambda s: s.number) if s.scene_id not in project.plan.scenes]

    def apply(scene_id, sp, err):
        nonlocal done
        _apply_scene_plan(project, scene_id, sp, err)
        done += 1
        if on_progress:
            on_progress("Planning scenes", done, total)

    run_parallel(missing, lambda sid: _plan_scene_call(project, sid, client, pack, scripts, cache), apply, settings.llm_concurrency)
    _finish(project, pack, scripts[project.selection.output_script])
    return project


def replan_scene(project: Project, scene_id: str, client: LLMClient, pack: CulturePack | None = None,
                 cache: JsonCache | None = None) -> Project:
    """Regenerate one scene only, bypassing the cache (an explicit "try again")."""
    pack, scripts = _setup(project, pack)
    if project.plan.entities is None:
        raise ValueError("no entity plan yet: call build_plan first")
    plan_scene(project, scene_id, client, pack, scripts, cache or default_cache("plan"), fresh=True)
    _finish(project, pack, scripts[project.selection.output_script])
    return project


def replan_entities(project: Project, client: LLMClient, pack: CulturePack | None = None,
                    cache: JsonCache | None = None) -> Project:
    """Regenerate the cast/costume/place plan (bypassing the cache). Scene plans depend on its names,
    so they are dropped and planned again."""
    pack, scripts = _setup(project, pack)
    project.plan.entities = None
    return build_plan(project, client, pack, cache, fresh_entities=True)
