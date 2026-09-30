"""Step 6: continuity checker. Pure code, no AI: the same records always give the same warnings.

It reads the canonical registry produced by normalization (holders per scene, costumes per
scene, state-change events) and reports contradictions BEFORE any image is generated.

Severity:
  ERROR    a hard contradiction; blocks approval until fixed or acknowledged as intentional
  WARNING  probably a problem, needs a human look
  INFO     something the visuals must respect (e.g. an injury that stays visible)

Every warning lists ALL affected scenes (from where the thing was last known to where it
breaks), so the reviewer sees the whole stretch, not just one scene.
"""
import logging

from app.models import (
    CharacterState,
    ContinuityWarning,
    Project,
    Severity,
    StateChangeKind,
)
from app.pipeline.normalize import norm_key

log = logging.getLogger(__name__)

K = StateChangeKind


def check_continuity(project: Project) -> list[ContinuityWarning]:
    """Recompute project.warnings and every scene's derived state. Idempotent."""
    if not project.scenes:
        raise ValueError("no canonical scenes: run normalization first")

    scenes = sorted(project.scenes, key=lambda s: s.number)
    index = {s.scene_id: i for i, s in enumerate(scenes)}
    char_name = {c.id: c.name for c in project.characters}
    prop_name = {p.id: p.name for p in project.props}
    costume = {c.id: c for c in project.costumes}
    old_ack = {w.id: (w.acknowledged, w.ack_note) for w in project.warnings}
    found: dict[str, ContinuityWarning] = {}

    def who(holder: str) -> str:
        return holder[1:] if holder.startswith("@") else char_name.get(holder, holder)

    def span(a: str, b: str) -> list[str]:
        lo, hi = sorted((index[a], index[b]))
        return [scenes[i].scene_id for i in range(lo, hi + 1)]

    def add(code: str, severity: Severity, message: str, entity: str | None, affected: list[str]) -> None:
        wid = f"{code}|{entity or ''}|{','.join(affected)}"
        found.setdefault(wid, ContinuityWarning(
            id=wid, code=code, severity=severity, message=message, entity_id=entity,
            affected_scene_ids=affected, acknowledged=old_ack.get(wid, (False, ""))[0],
            ack_note=old_ack.get(wid, (False, ""))[1]))

    # ---- structure: missing scenes, missing locations ------------------------------------
    source_numbers = {s.number for s in project.source_scenes}
    have = {s.number for s in scenes}
    if source_numbers and source_numbers != have:
        gone = sorted(source_numbers - have)
        add("SCENE_MISSING", Severity.ERROR,
            f"source scene(s) {gone} are missing from the canonical records", None,
            [f"SC{n:02d}" for n in gone])
    expected = list(range(1, max(have) + 1))
    if sorted(have) != expected:
        add("SCENE_GAP", Severity.ERROR, f"scene numbers are not contiguous: {sorted(have)}", None,
            [s.scene_id for s in scenes])
    for s in scenes:
        if not s.location_id:
            add("MISSING_LOCATION", Severity.ERROR, f"{s.scene_id} has no location", None, [s.scene_id])
        if not s.characters:
            add("NO_CHARACTERS", Severity.WARNING, f"{s.scene_id} has no characters", None, [s.scene_id])

    # ---- props: who holds what, scene to scene -------------------------------------------
    for prop in project.props:
        pname = prop_name[prop.id]
        prev_holder, prev_scene = "", ""
        for s in scenes:
            if s.scene_id not in prop.scene_ids:
                continue
            start = s.prop_holder_start.get(prop.id, "")
            end = s.prop_holder_end.get(prop.id, "")

            if prev_holder and start and start != prev_holder:
                explained = any(
                    e.item == prop.id and (
                        (e.kind == K.PROP_GAIN and e.character_id == start)
                        or (e.kind == K.PROP_TRANSFER and e.to_character_id == start))
                    for e in s.state_changes)
                if not explained:
                    hard = not prev_holder.startswith("@") and not start.startswith("@")
                    gap = index[s.scene_id] - index[prev_scene] - 1
                    between = (f" ({gap} scene(s) in between do not mention it)" if gap > 0 else "")
                    add("PROP_HOLDER_MISMATCH", Severity.ERROR if hard else Severity.WARNING,
                        f"the {pname}: {prev_scene} ends with {who(prev_holder)} holding it, but "
                        f"{s.scene_id} starts with {who(start)} holding it, and nothing explains "
                        f"the handover{between}",
                        prop.id, span(prev_scene, s.scene_id))

            if end:
                prev_holder, prev_scene = end, s.scene_id
                # the holder is in the very next scene but the prop is not mentioned there
                nxt = scenes[index[s.scene_id] + 1] if index[s.scene_id] + 1 < len(scenes) else None
                if nxt and end in nxt.characters and nxt.scene_id not in prop.scene_ids:
                    add("PROP_NOT_SHOWN", Severity.WARNING,
                        f"{who(end)} has the {pname} at the end of {s.scene_id} and is in {nxt.scene_id}, "
                        f"but the {pname} is not mentioned there",
                        prop.id, [s.scene_id, nxt.scene_id])
            elif start:
                prev_holder, prev_scene = start, s.scene_id  # end unknown: assume unchanged

    # ---- prop handovers must agree with the recorded holders ------------------------------
    for s in scenes:
        for e in s.state_changes:
            if e.kind != K.PROP_TRANSFER or e.item not in prop_name:
                continue
            start = s.prop_holder_start.get(e.item, "")
            end = s.prop_holder_end.get(e.item, "")
            pn = prop_name[e.item]
            if start and start != e.character_id:
                add("TRANSFER_SOURCE_MISMATCH", Severity.WARNING,
                    f"{s.scene_id}: {char_name.get(e.character_id)} hands over the {pn}, but "
                    f"{who(start)} is recorded holding it at the start", e.item, [s.scene_id])
            if end and e.to_character_id and end != e.to_character_id:
                add("TRANSFER_TARGET_MISMATCH", Severity.WARNING,
                    f"{s.scene_id}: the {pn} is handed to {char_name.get(e.to_character_id)}, but "
                    f"{who(end)} is recorded holding it at the end", e.item, [s.scene_id])

    # ---- costumes: keep one until the story gives a reason --------------------------------
    for c in project.characters:
        prev = None
        for s in scenes:
            cid = s.costumes.get(c.id)
            if cid is None:
                continue
            if prev and cid != prev[1] and not costume[cid].change_reason:
                same_time = norm_key(s.time) == norm_key(next(x for x in scenes if x.scene_id == prev[0]).time)
                add("COSTUME_CHANGE_NO_REASON", Severity.ERROR if same_time else Severity.WARNING,
                    f"{c.name} wears {costume[prev[1]].garments or prev[1]} in {prev[0]} but "
                    f"{costume[cid].garments or cid} in {s.scene_id}, and the story gives no reason"
                    + ("" if same_time else " (time has passed, so a change is plausible, but it is unexplained)"),
                    c.id, span(prev[0], s.scene_id))
            prev = (s.scene_id, cid)

    # ---- derived state per scene: injuries and knowledge persist ---------------------------
    injuries: dict[str, list[str]] = {}
    knows: dict[str, list[str]] = {}
    gained_in: dict[tuple[str, str], str] = {}  # (char, injury) -> scene where it started
    for s in scenes:
        for e in s.state_changes:
            active = injuries.setdefault(e.character_id, [])
            if e.kind == K.INJURY_GAIN and e.item:
                if norm_key(e.item) not in [norm_key(x) for x in active]:
                    active.append(e.item)
                    gained_in[(e.character_id, norm_key(e.item))] = s.scene_id
            elif e.kind == K.INJURY_HEAL:
                match = next((x for x in active if norm_key(x) == norm_key(e.item)
                              or norm_key(e.item) in norm_key(x) or norm_key(x) in norm_key(e.item)), None)
                if match:
                    active.remove(match)
                else:
                    add("INJURY_HEAL_WITHOUT_INJURY", Severity.WARNING,
                        f"{s.scene_id}: {char_name.get(e.character_id)} is healed of {e.item!r}, "
                        "but no earlier scene injures them", e.character_id, [s.scene_id])
            elif e.kind == K.KNOWLEDGE_GAIN and e.item:
                k = knows.setdefault(e.character_id, [])
                if e.item not in k:
                    k.append(e.item)

        s.states = {}
        for cid in s.characters:
            held = {**s.prop_holder_start, **s.prop_holder_end}  # end holder wins where known
            carrying = [p for p in held if (s.prop_holder_end.get(p) or s.prop_holder_start.get(p)) == cid]
            s.states[cid] = CharacterState(
                costume_id=s.costumes.get(cid, ""), carrying=carrying,
                injuries=list(injuries.get(cid, [])), knows=list(knows.get(cid, [])))

    # an injury that stays active must stay visible in every later scene the person is in
    for (cid, injury_key), start_scene in gained_in.items():
        item = next((x for x in injuries.get(cid, []) if norm_key(x) == injury_key), None)
        if item is None:
            continue  # healed
        later = [s.scene_id for s in scenes if index[s.scene_id] > index[start_scene] and cid in s.characters]
        if later:
            add("INJURY_ACTIVE", Severity.INFO,
                f"{char_name.get(cid)} gets {item!r} in {start_scene} and it is never healed, so it must "
                f"stay visible in {', '.join(later)}", cid, [start_scene, *later])

    # ---- publish ---------------------------------------------------------------------------
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    project.warnings = sorted(found.values(), key=lambda w: (order[w.severity], w.code, w.affected_scene_ids))
    for s in scenes:
        s.continuity_warnings = [w.id for w in project.warnings if s.scene_id in w.affected_scene_ids]
    project.continuity_checked = True
    log.info("continuity: %d error(s), %d warning(s), %d info", *(
        sum(w.severity == sev for w in project.warnings) for sev in (Severity.ERROR, Severity.WARNING, Severity.INFO)))
    return project.warnings
