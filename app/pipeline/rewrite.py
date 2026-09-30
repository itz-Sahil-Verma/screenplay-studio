"""Step 10: rewrite the screenplay inside the culture, in the chosen script.

One model call per scene, from APPROVED material only: the applied records, the accepted decisions and
the scene plan. Story preservation and traceability are enforced by code, not trusted:
  * every source dialogue line is numbered; each adapted dialogue line names the one it adapts, must have the
    same speaker, and the order must not change; every source line must be adapted at least once;
  * every source event (a handover, an injury, a piece of news) must be depicted, by number;
  * every line must be written in the output script only (English loanwords transliterated), never mixing
    scripts inside a word, and carries an English gloss so a reviewer can check what it says;
  * cited decision ids must exist.
Anything still wrong after the retry budget is kept but flagged on the scene for the reviewer.
"""
import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.culture_packs.loader import load_pack, load_scripts
from app.llm.base import LLMClient
from app.models import (AdaptedLine, AdaptedScene, CulturePack, LineKind, Project, ProjectStatus, ReviewStatus, Scene,
                        ScriptInfo)
from app.pipeline.culture_checks import avoid_problems
from app.pipeline.normalize import _HEAD, norm_key
from app.pipeline.plan import _ask, _english_problem, _malformed_words, _mixed_script_words, _script_problem
from app.pipeline.extract import client_id
from app.config import settings
from app.pipeline.parallel import run_parallel
from app.storage import JsonCache, default_cache

log = logging.getLogger(__name__)


class LineDraft(BaseModel):
    kind: Literal["dialogue", "action", "gesture", "sound"]
    character_id: str = ""  # required for dialogue: who speaks
    text: str  # in the OUTPUT SCRIPT only
    gloss: str  # what it says/shows, in plain English, for a reviewer who cannot read the script
    source_line: int = 0  # dialogue: the number of the SOURCE DIALOGUE LINE this adapts
    event_ids: list[int] = Field(default_factory=list)  # numbers of the SOURCE EVENTS this line depicts
    decision_ids: list[str] = Field(default_factory=list)  # DEC ids that shaped this line
    uncertain: bool = False
    note: str = ""


class SceneRewrite(BaseModel):
    scene_id: str
    heading: str  # the slugline written in the OUTPUT SCRIPT (INT/EXT translated), with the adapted place
    lines: list[LineDraft]


SYSTEM = """You are a screenwriter who re-creates one scene of a screenplay INSIDE a specific culture, in its own language, described in the CULTURE PACK. This is not a translation: dialogue must carry the dialect's rhythm, humour, kinship terms, honorifics and politeness; behaviour, gestures, objects, food and sound must belong to the region.

Rules:
- PRESERVE THE STORY. Every SOURCE DIALOGUE LINE must be adapted by at least one dialogue line whose source_line is its number and whose speaker (character_id) is the same person, in the SAME ORDER as the source. Every SOURCE EVENT must be shown: put its number in event_ids on the line that shows it. Do not add plot events that no ACCEPTED DECISION calls for. A dialogue line that adapts NO source line (source_line 0) is allowed only when an ACCEPTED DECISION calls for it, and it must cite that decision in decision_ids.
- Follow the ACCEPTED DECISIONS and the SCENE PLAN. If a decision changes a source event, follow the decision and say so in note. Cite the DEC ids that shaped a line in decision_ids.
- SCRIPT: write text (dialogue AND action, gesture and sound lines) ONLY in the OUTPUT SCRIPT. No Latin letters at all: an English loanword must be transliterated into the script. Never mix scripts inside one word. Use each character's native name exactly as given.
- heading: the scene heading (slugline) written in the OUTPUT SCRIPT, with INT/EXT translated and the adapted place.
- gloss and note: written in plain ENGLISH, so a reviewer who cannot read the script can check them. The gloss renders what the line says or shows.
- Spelling: write every word in its standard, correct spelling in the script; prefer the pack's own spellings of its terms. Avoid words borrowed from another language's spelling conventions.
- kinds: dialogue (spoken, needs character_id), action (what we see happen), gesture (non-verbal behaviour), sound (sound and music cues).
- Set uncertain=true, with a note, whenever you are unsure of a word, its spelling in the script, or whether it belongs to this dialect. Never guess quietly.
- Use only the ids given. Use the pack's facts and RULEs; do not assume a religion; do not import words or objects from other regions or dialects.
- Output valid JSON for the given schema and nothing else."""

_CUE = re.compile(r"^[A-Z][A-Z .'\-]{0,38}(?:\s*\([^)]*\))?$")


_TITLES = {"mr", "mrs", "ms", "miss", "dr", "sir", "master", "mister", "uncle", "aunty", "aunt", "ji", "the"}


def speaker_lookup(project: Project) -> dict[str, str]:
    """Maps the names a screenplay uses in dialogue cues to character ids. A cue is usually shorter than the name
    the character was introduced with ("DESAI" for "MR. DESAI"), so besides every full name and alias, a single word
    of a name also resolves to its character, but only if that word belongs to exactly one character and is not a
    title. An ambiguous cue stays unresolved (None) instead of being guessed."""
    lookup: dict[str, str] = {}
    owners: dict[str, set[str]] = {}
    for c in project.characters:
        for n in [c.name, *c.aliases]:
            k = norm_key(n)
            lookup[k] = c.id
            for word in k.split():
                if len(word) >= 3 and word not in _TITLES:
                    owners.setdefault(word, set()).add(c.id)
    for word, ids in owners.items():
        if len(ids) == 1:
            lookup.setdefault(word, next(iter(ids)))
    return lookup


def source_dialogue(project: Project, scene: Scene) -> list[tuple[str | None, str]]:
    """The scene's source dialogue as (speaker character id or None, text), in order. Rule-based."""
    lookup = speaker_lookup(project)
    lines, out, i = scene.source_text.split("\n"), [], 0
    prev_speaker, prev_end = None, -1  # to merge a "(CONT'D)" that only exists because of a page break
    while i < len(lines):
        ln = lines[i].strip()
        if ln and _CUE.match(ln) and not _HEAD.match(ln) and i + 1 < len(lines) and lines[i + 1].strip():
            speaker = re.sub(r"\s*\([^)]*\)$", "", ln)
            block, j = [], i + 1
            while j < len(lines) and lines[j].strip():
                block.append(lines[j].strip())
                j += 1
            text = " ".join(block)
            same = prev_speaker is not None and norm_key(speaker) == prev_speaker
            nothing_between = prev_end >= 0 and all(not x.strip() for x in lines[prev_end:i])
            if re.search(r"\(\s*CONT[\u2019']D\s*\)", ln, re.I) and same and nothing_between and out:
                out[-1] = (out[-1][0], out[-1][1] + " " + text)  # the same speech, split by a page break
            else:
                out.append((lookup.get(norm_key(speaker)), text))
            prev_speaker, prev_end = norm_key(speaker), j
            i = j
        else:
            i += 1
    return out


def describe_events(project: Project, scene: Scene) -> list[str]:
    name = {c.id: c.name for c in project.characters}
    pname = {p.id: p.name for p in project.props}
    out = []
    for e in scene.state_changes:
        item = pname.get(e.item, e.item)
        to = f" to {name.get(e.to_character_id, e.to_character_id)}" if e.to_character_id else ""
        out.append(f"{e.kind.value}: {name.get(e.character_id, e.character_id)}: {item}{to}")
    return out


def rewrite_prompt(project: Project, pack: CulturePack, scripts: dict[str, ScriptInfo], scene: Scene) -> str:
    sel, plan = project.selection, project.plan
    dump = lambda o: json.dumps(o, ensure_ascii=False, indent=1)
    garment = {c.id: c.garments for c in project.costumes}
    cast = [{"id": c.id, "name_roman": c.adapted_name, "name_native": c.adapted_name_native,
             "role": c.role_adapted, "speech_register": c.speech_register, "address_terms": c.address_terms,
             "wearing": garment.get(scene.costumes.get(c.id, ""), "")}
            for c in project.characters if c.id in scene.characters]
    loc = next((l for l in project.locations if l.id == scene.location_id), None)
    props = [{"id": p.id, "name_roman": p.adapted_name, "name_native": p.adapted_name_native,
              "description": p.description} for p in project.props if p.id in {*scene.prop_holder_start, *scene.prop_holder_end}]
    sp = plan.scenes[scene.scene_id]
    decisions = [{"id": d.id, "dimension": d.dimension.value, "original": d.original, "adapted": d.adapted,
                  "reason": d.reason, "flagged": d.uncertain}
                 for d in project.decisions
                 if d.status != ReviewStatus.REJECTED and (scene.scene_id in d.source_scene_ids or d.entity_id in
                                                          {*scene.characters, *scene.costumes.values(), scene.location_id})]
    dialogue = [f"{i}. [{project.character(sp_id).name if sp_id else '?'} / {sp_id}] {t}"
                for i, (sp_id, t) in enumerate(source_dialogue(project, scene), 1)]
    events = [f"{i}. {d}" for i, d in enumerate(describe_events(project, scene), 1)]
    return "\n".join([
        "=== CULTURE PACK ===", pack.for_prompt(), "",
        f"=== TARGET ===\nRegion: {sel.region}. Setting: {sel.setting.value}. "
        f"OUTPUT SCRIPT: {scripts[sel.output_script].label} (all `text` fields in this script only).", "",
        "=== WORLD (same for every scene) ===", plan.entities.season_and_period, "",
        "=== CAST IN THIS SCENE (use these names) ===", dump(cast),
        "=== PLACE ===", dump({"id": scene.location_id, "name": loc.adapted_name if loc else "", "description": loc.description if loc else ""}),
        "=== PROPS ===", dump(props),
        "=== SCENE PLAN ===", dump({"setting_notes": sp.setting_notes, "dialogue_notes": sp.dialogue_notes,
                                    "gestures": sp.gestures, "food": sp.food, "sound_music": sp.sound_music, "rituals": sp.rituals}),
        "=== ACCEPTED DECISIONS ===", dump(decisions), "",
        "=== SOURCE DIALOGUE LINES (each must be adapted, in this order) ===", "\n".join(dialogue) or "(none)", "",
        "=== SOURCE EVENTS (each must be shown) ===", "\n".join(events) or "(none)", "",
        "=== SOURCE SCENE TEXT ===", scene.source_text, "=== END ===",
        f"Set scene_id to {scene.scene_id!r}.",
    ])


def verify_rewrite(project: Project, script: ScriptInfo, scene: Scene, sr: SceneRewrite, pack: CulturePack | None = None) -> list[str]:
    problems: list[str] = []
    if sr.scene_id != scene.scene_id:
        problems.append(f"scene_id is {sr.scene_id!r}, expected {scene.scene_id!r}")
    msg = _script_problem(sr.heading, script, "heading")
    if msg:
        problems.append(msg + " (the heading must be in the output script)")
    if not sr.lines:
        problems.append("no lines")
    src = source_dialogue(project, scene)
    n_events = len(scene.state_changes)
    known_decisions = {d.id for d in project.decisions}
    chars_here = set(scene.characters)
    covered_lines, covered_events, last = set(), set(), 0
    for i, ln in enumerate(sr.lines, 1):
        tag = f"line {i} ({ln.kind})"
        msg = _script_problem(ln.text, script, f"{tag} text")
        if msg:
            problems.append(msg + " (write it in the output script only; transliterate English words)")
        if pack is not None:
            problems += avoid_problems(ln.text, pack, f"{tag} text")
        bad = _mixed_script_words(ln.text)
        if bad:
            problems.append(f"{tag} text mixes scripts inside a word: {bad[:3]}")
        broken = _malformed_words(ln.text)
        if broken:
            problems.append(f"{tag} text has malformed word(s) that start with a vowel sign: {broken[:3]} (fix the spelling)")
        if ln.note.strip():
            msg = _english_problem(ln.note, f"{tag} note", max_native=0.15)
            if msg:
                problems.append(msg)
        if not ln.gloss.strip():
            problems.append(f"{tag}: gloss is empty")
        else:
            msg = _english_problem(ln.gloss, f"{tag} gloss", max_native=0.15)
            if msg:
                problems.append(msg)
        bad_dec = [d for d in ln.decision_ids if d not in known_decisions]
        if bad_dec:
            problems.append(f"{tag} cites decisions that do not exist: {bad_dec}")
        bad_ev = [e for e in ln.event_ids if not 1 <= e <= n_events]
        if bad_ev:
            problems.append(f"{tag} cites event numbers that do not exist: {bad_ev}")
        covered_events.update(e for e in ln.event_ids if 1 <= e <= n_events)
        if ln.character_id and ln.character_id not in {c.id for c in project.characters}:
            problems.append(f"{tag}: unknown character_id {ln.character_id!r}")
        if ln.kind == "dialogue":
            if not ln.character_id:
                problems.append(f"{tag}: dialogue needs a character_id")
            elif ln.character_id not in chars_here:
                problems.append(f"{tag}: {ln.character_id} is not in this scene")
            if ln.source_line == 0:
                if not ln.decision_ids:
                    problems.append(f"{tag}: adapts no source line and cites no decision: added dialogue must be called for by an accepted decision")
            elif not 1 <= ln.source_line <= len(src):
                problems.append(f"{tag}: source_line {ln.source_line} is not one of the {len(src)} source dialogue lines")
            else:
                speaker = src[ln.source_line - 1][0]
                if speaker and ln.character_id and speaker != ln.character_id:
                    problems.append(f"{tag}: source line {ln.source_line} is spoken by {speaker}, not {ln.character_id}")
                if ln.source_line < last:
                    problems.append(f"{tag}: source line {ln.source_line} comes after line {last}: do not reorder the dialogue")
                last = max(last, ln.source_line)
                covered_lines.add(ln.source_line)
    lost = sorted(set(range(1, len(src) + 1)) - covered_lines)
    if lost:
        problems.append(f"source dialogue line(s) {lost} were not adapted (every line must appear)")
    unshown = sorted(set(range(1, n_events + 1)) - covered_events)
    if unshown:
        problems.append(f"source event(s) {unshown} are not shown (list their numbers in event_ids)")
    return problems


def _to_adapted(scene: Scene, sr: SceneRewrite, problems: list[str]) -> AdaptedScene:
    return AdaptedScene(
        source_scene_id=scene.scene_id, heading=sr.heading.strip(), problems=problems,
        lines=[AdaptedLine(source_scene_id=scene.scene_id, decision_ids=l.decision_ids, character_id=l.character_id or None,
                           kind=LineKind(l.kind), text=l.text, gloss=l.gloss, source_line=l.source_line or None,
                           event_ids=l.event_ids, uncertain=l.uncertain, note=l.note) for l in sr.lines])


def _setup(project: Project, pack: CulturePack | None):
    if project.status not in (ProjectStatus.APPROVED, ProjectStatus.REWRITTEN):
        raise ValueError(f"the rewrite needs an approved project, not {project.status.value}: "
                         "approve characters, costumes and plan first")
    pack = pack or load_pack(project.selection.pack_id)
    return pack, load_scripts()


def _rewrite_call(project: Project, scene: Scene, client: LLMClient, pack: CulturePack, scripts, cache: JsonCache | None,
                  fresh: bool = False) -> AdaptedScene:
    """The model call for one scene. Read-only on the project, so it is safe to run in a worker thread."""
    script = scripts[project.selection.output_script]
    sr, problems = _ask(client, cache or default_cache("rewrite"), SYSTEM, rewrite_prompt(project, pack, scripts, scene),
                        SceneRewrite, lambda r: verify_rewrite(project, script, scene, r, pack), fresh)
    sr.scene_id = scene.scene_id  # code owns ids
    return _to_adapted(scene, sr, problems if problems else verify_rewrite(project, script, scene, sr, pack))


def _apply_rewrite(project: Project, scene_id: str, adapted: AdaptedScene | None, error: Exception | None) -> None:
    """Record one scene's outcome. Runs on a single thread; a failure here never touches the other scenes."""
    project.adapted_scenes = [a for a in project.adapted_scenes if a.source_scene_id != scene_id]
    if error is None and adapted is not None:
        project.adapted_scenes.append(adapted)
        project.adapted_scenes.sort(key=lambda a: a.source_scene_id)
        project.rewrite_failed.pop(scene_id, None)
    else:
        project.rewrite_failed[scene_id] = f"{type(error).__name__}: {str(error)[:300]}"
        log.error("rewrite of %s failed: %s", scene_id, project.rewrite_failed[scene_id])


def rewrite_scene(project: Project, scene_id: str, client: LLMClient, pack: CulturePack | None = None,
                  cache: JsonCache | None = None, fresh: bool = False) -> AdaptedScene | None:
    """(Re)write one scene. On failure the error is recorded on the project and the other scenes are untouched."""
    pack, scripts = _setup(project, pack)
    scene = next(s for s in project.scenes if s.scene_id == scene_id)
    try:
        adapted, err = _rewrite_call(project, scene, client, pack, scripts, cache, fresh), None
    except Exception as e:  # noqa: BLE001: recorded per scene
        adapted, err = None, e
    _apply_rewrite(project, scene_id, adapted, err)
    return adapted


def rewrite_screenplay(project: Project, client: LLMClient, pack: CulturePack | None = None,
                       cache: JsonCache | None = None, on_progress=None) -> Project:
    """Rewrite every scene that has no rewrite yet. Re-running only redoes what is missing or failed.
    Scenes are independent once the plan is approved, so they run concurrently (LLM_CONCURRENCY)."""
    pack, scripts = _setup(project, pack)
    have = {a.source_scene_id for a in project.adapted_scenes}
    scenes = [s for s in sorted(project.scenes, key=lambda s: s.number) if s.scene_id not in have]
    done = 0

    def apply(scene, adapted, err):
        nonlocal done
        _apply_rewrite(project, scene.scene_id, adapted, err)
        done += 1
        if on_progress:
            on_progress("Writing scenes", done, len(scenes))

    run_parallel(scenes, lambda s: _rewrite_call(project, s, client, pack, scripts, cache), apply, settings.llm_concurrency)
    if not project.rewrite_failed and len(project.adapted_scenes) == len(project.scenes) and project.status == ProjectStatus.APPROVED:
        project.transition(ProjectStatus.REWRITTEN)
    return project


def screenplay_text(project: Project, with_gloss: bool = False) -> str:
    """The adapted screenplay as readable text: sluglines, action, character cues and dialogue."""
    name = {c.id: (c.adapted_name_native or c.name) for c in project.characters}
    out: list[str] = []
    for a in sorted(project.adapted_scenes, key=lambda a: a.source_scene_id):
        out += [a.heading, ""]
        for ln in a.lines:
            g = f"   [{ln.gloss}]" if with_gloss and ln.gloss else ""
            mark = " (?)" if ln.uncertain else ""
            if ln.kind == LineKind.DIALOGUE:
                out += [f"        {name.get(ln.character_id or '', ln.character_id or '')}", f"    {ln.text}{mark}{g}", ""]
            elif ln.kind == LineKind.SOUND:
                out += [f"({ln.text}){mark}{g}", ""]
            else:
                out += [f"{ln.text}{mark}{g}", ""]
    return "\n".join(out).rstrip() + "\n"
