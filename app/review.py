"""Step 9: human review and approval. Everything a person can change goes through here.

Rules enforced in one place (so the API, and any future UI, cannot bypass them):
  * Any edit reopens the gate: approvals are cleared, a project past `plan_ready` steps back to
    it, generated images become stale, the continuity check is re-run, and the plan is
    re-verified. The edit returns the scenes it affects, so only those need regenerating.
  * Nothing is approved implicitly. Characters, costumes and plan are approved separately, each
    with an explicit list of blockers. When all three are approved (and no continuity error is
    left unresolved) the project becomes `approved` and the approved plan is applied to the
    canonical records.
  * A merge that would join two people who share a scene is refused.
"""
import re

from app.culture_packs.loader import load_pack, load_scripts
from app.models import (
    Approval,
    CharacterPlan,
    CostumePlan,
    GateError,
    LocationPlan,
    Project,
    ProjectStatus,
    PropPlan,
    ReviewStatus,
    Severity,
)
from app.pipeline.continuity import check_continuity
from app.pipeline.normalize import norm_key
from app.pipeline.plan import all_problems, flatten_decisions, iter_drafts


class ReviewError(ValueError):
    """The requested change is not valid (unknown id, forbidden merge, bad field...)."""


PAST_PLAN = (ProjectStatus.APPROVED, ProjectStatus.REWRITTEN, ProjectStatus.GENERATED, ProjectStatus.EXPORTED)
PLAN_MODELS = {"character": (CharacterPlan, "character_id"), "costume": (CostumePlan, "costume_id"),
               "location": (LocationPlan, "location_id"), "prop": (PropPlan, "prop_id")}


# ---- shared machinery ----------------------------------------------------------------------------
def _scene_order(project: Project, ids) -> list[str]:
    return [s.scene_id for s in sorted(project.scenes, key=lambda s: s.number) if s.scene_id in set(ids)]


def _refresh_plan(project: Project) -> None:
    """Re-verify the plan against the current records and rebuild the reviewable decisions."""
    if project.plan is None or project.selection is None:
        return
    pack, scripts = load_pack(project.selection.pack_id), load_scripts()
    project.plan.problems = all_problems(project, pack, scripts[project.selection.output_script])
    if project.plan.entities is not None:
        project.decisions = flatten_decisions(project, pack)


def _touch(project: Project, what: str, scene_ids) -> list[str]:
    """Called after EVERY change to records or plan. Returns the affected scenes, in story order."""
    affected = _scene_order(project, scene_ids)
    project.user_edits.append(what)
    project.reopen()  # clears approvals, steps back to plan_ready, marks generated images stale
    if project.plan is not None:
        for sid in affected:
            if sid in project.plan.scenes and sid not in project.plan.stale_scenes:
                project.plan.stale_scenes.append(sid)
    check_continuity(project)
    _refresh_plan(project)
    return affected


def _get(collection, item_id: str, label: str):
    item = next((x for x in collection if x.id == item_id), None)
    if item is None:
        raise ReviewError(f"unknown {label} {item_id!r}")
    return item


def _dedupe_names(names: list[str], exclude: str) -> list[str]:
    seen, out = {norm_key(exclude)}, []
    for n in names:
        k = norm_key(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def _drop_plan_entry(project: Project, kind: str, entity_id: str) -> None:
    if project.plan is None or project.plan.entities is None:
        return
    coll = {"character": project.plan.entities.characters, "costume": project.plan.entities.costumes,
            "location": project.plan.entities.locations, "prop": project.plan.entities.props}[kind]
    id_field = PLAN_MODELS[kind][1]
    coll[:] = [e for e in coll if getattr(e, id_field) != entity_id]


def _remap_decision_entity(project: Project, old: str, new: str) -> None:
    if project.plan is None:
        return
    drafts = [d for d, _ in iter_drafts(project)] if project.plan.entities else []
    for d in drafts:
        if d.entity_id == old:
            d.entity_id = new


# ---- edits to extracted records ----------------------------------------------------------------------
def edit_character(project: Project, char_id: str, **fields) -> list[str]:
    allowed = {"name", "aliases", "age", "role", "personality"}
    bad = set(fields) - allowed
    if bad:
        raise ReviewError(f"cannot edit {sorted(bad)}; allowed: {sorted(allowed)}")
    c = _get(project.characters, char_id, "character")
    if "name" in fields and not str(fields["name"]).strip():
        raise ReviewError("name cannot be empty")
    for k, v in fields.items():
        setattr(c, k, v)
    return _touch(project, f"edited character {char_id}: {sorted(fields)}", c.scene_ids)


def merge(project: Project, kind: str, keep_id: str, drop_id: str) -> list[str]:
    """Merge `drop` into `keep` (kind: character | prop | location | costume). All references follow."""
    if keep_id == drop_id:
        raise ReviewError("cannot merge a record into itself")
    fn = {"character": _merge_characters, "prop": _merge_props, "location": _merge_locations,
          "costume": _merge_costumes}.get(kind)
    if fn is None:
        raise ReviewError(f"unknown kind {kind!r}")
    affected = fn(project, keep_id, drop_id)
    _drop_plan_entry(project, kind, drop_id)
    _remap_decision_entity(project, drop_id, keep_id)
    return _touch(project, f"merged {kind} {drop_id} into {keep_id}", affected)


def _merge_characters(project: Project, keep_id: str, drop_id: str) -> list[str]:
    keep = _get(project.characters, keep_id, "character")
    drop = _get(project.characters, drop_id, "character")
    shared = sorted(set(keep.scene_ids) & set(drop.scene_ids))
    if shared:
        raise ReviewError(f"{keep_id} and {drop_id} appear together in {shared}, so they are different people")
    keep.aliases = _dedupe_names([*keep.aliases, drop.name, *drop.aliases], keep.name)
    keep.scene_ids = _scene_order(project, [*keep.scene_ids, *drop.scene_ids])
    keep.age = keep.age or drop.age
    keep.role = keep.role or drop.role
    keep.relationship_notes = list(dict.fromkeys([*keep.relationship_notes, *drop.relationship_notes]))
    project.characters.remove(drop)
    for c in project.costumes:
        if c.character_id == drop_id:
            c.character_id = keep_id
    swap = lambda x: keep_id if x == drop_id else x
    for s in project.scenes:
        s.characters = list(dict.fromkeys(swap(c) for c in s.characters))
        s.entrances = list(dict.fromkeys(swap(c) for c in s.entrances))
        s.exits = list(dict.fromkeys(swap(c) for c in s.exits))
        if drop_id in s.costumes:
            s.costumes.setdefault(keep_id, s.costumes[drop_id])
            del s.costumes[drop_id]
        s.prop_holder_start = {p: swap(h) for p, h in s.prop_holder_start.items()}
        s.prop_holder_end = {p: swap(h) for p, h in s.prop_holder_end.items()}
        for e in s.state_changes:
            e.character_id, e.to_character_id = swap(e.character_id), (swap(e.to_character_id) if e.to_character_id else None)
    return list(keep.scene_ids)


def _merge_props(project: Project, keep_id: str, drop_id: str) -> list[str]:
    keep, drop = _get(project.props, keep_id, "prop"), _get(project.props, drop_id, "prop")
    keep.aliases = _dedupe_names([*keep.aliases, drop.name, *drop.aliases], keep.name)
    keep.scene_ids = _scene_order(project, [*keep.scene_ids, *drop.scene_ids])
    keep.description = keep.description or drop.description
    project.props.remove(drop)
    for s in project.scenes:
        for holders in (s.prop_holder_start, s.prop_holder_end):
            if drop_id in holders:
                holders.setdefault(keep_id, holders[drop_id])
                del holders[drop_id]
        s.props_in = list(dict.fromkeys(keep_id if p == drop_id else p for p in s.props_in))
        s.props_out = list(dict.fromkeys(keep_id if p == drop_id else p for p in s.props_out))
        for e in s.state_changes:
            if e.item == drop_id:
                e.item = keep_id
    return list(keep.scene_ids)


def _merge_locations(project: Project, keep_id: str, drop_id: str) -> list[str]:
    keep, drop = _get(project.locations, keep_id, "location"), _get(project.locations, drop_id, "location")
    keep.sub_locations = _dedupe_names([*keep.sub_locations, *drop.sub_locations], "")
    keep.scene_ids = _scene_order(project, [*keep.scene_ids, *drop.scene_ids])
    keep.description = keep.description or drop.description
    project.locations.remove(drop)
    for s in project.scenes:
        if s.location_id == drop_id:
            s.location_id = keep_id
    return list(keep.scene_ids)


def _merge_costumes(project: Project, keep_id: str, drop_id: str) -> list[str]:
    keep, drop = _get(project.costumes, keep_id, "costume"), _get(project.costumes, drop_id, "costume")
    if keep.character_id != drop.character_id:
        raise ReviewError(f"{keep_id} and {drop_id} belong to different characters")
    keep.scene_ids = _scene_order(project, [*keep.scene_ids, *drop.scene_ids])
    keep.change_reason = keep.change_reason or drop.change_reason
    project.costumes.remove(drop)
    for s in project.scenes:
        for cid, costume_id in list(s.costumes.items()):
            if costume_id == drop_id:
                s.costumes[cid] = keep_id
    return list(keep.scene_ids)


# ---- edits to the plan --------------------------------------------------------------------------------
def edit_plan_entity(project: Project, kind: str, entity_id: str, **fields) -> list[str]:
    """Correct the model's plan for one character/costume/location/prop (e.g. rename, fix a garment)."""
    if kind not in PLAN_MODELS:
        raise ReviewError(f"unknown kind {kind!r}")
    if project.plan is None or project.plan.entities is None:
        raise ReviewError("there is no plan yet")
    model, id_field = PLAN_MODELS[kind]
    coll = {"character": project.plan.entities.characters, "costume": project.plan.entities.costumes,
            "location": project.plan.entities.locations, "prop": project.plan.entities.props}[kind]
    entry = next((e for e in coll if getattr(e, id_field) == entity_id), None)
    if entry is None:
        raise ReviewError(f"the plan has no {kind} {entity_id!r}")
    bad = set(fields) - (set(model.model_fields) - {id_field})
    if bad:
        raise ReviewError(f"cannot edit {sorted(bad)} on a {kind} plan")
    try:
        updated = model.model_validate({**entry.model_dump(), **fields})
    except ValueError as e:
        raise ReviewError(str(e)) from e
    coll[coll.index(entry)] = updated
    scenes = next((r.scene_ids for r in (project.characters + project.costumes + project.locations + project.props)
                   if r.id == entity_id), [])
    return _touch(project, f"edited plan {kind} {entity_id}: {sorted(fields)}", scenes)


def keep_scene_plan(project: Project, scene_id: str) -> None:
    """The reviewer looked at an edit's effect on this scene and decides its existing plan still stands.
    The alternative is re-planning it (a model call). Either way the choice is explicit."""
    if project.plan is None or scene_id not in project.plan.stale_scenes:
        raise ReviewError(f"{scene_id} is not waiting on a re-plan")
    project.plan.stale_scenes.remove(scene_id)
    project.approval.plan = False  # the plan approval must be given again
    project.user_edits.append(f"kept the existing plan for {scene_id} after an edit")


def review_decision(project: Project, decision_id: str, status: str, adapted: str | None = None,
                    note: str = "") -> None:
    """Accept, reject or edit one decision. An edit rewrites the plan itself, so it survives regeneration."""
    try:
        st = ReviewStatus(status)
    except ValueError as e:
        raise ReviewError(f"status must be one of {[s.value for s in ReviewStatus]}") from e
    idx = next((i for i, d in enumerate(project.decisions) if d.id == decision_id), None)
    if idx is None:
        raise ReviewError(f"unknown decision {decision_id!r}")
    if adapted is not None:
        if not adapted.strip():
            raise ReviewError("the adapted text cannot be empty")
        iter_drafts(project)[idx][0].adapted = adapted
        st = ReviewStatus.EDITED
    if adapted is not None or project.status in PAST_PLAN:
        project.reopen()  # the plan itself changed (or an approved plan was second-guessed): approve again
    else:
        project.approval.plan = False  # only the plan approval is affected; characters/costumes stand
    if adapted is not None:
        _refresh_plan(project)  # re-verify + re-flatten, keeping review state of the others
    dec = project.decisions[idx]
    dec.status, dec.reviewer_note = st, note
    if adapted is not None:
        dec.adapted = adapted


def acknowledge_warning(project: Project, warning_id: str, acknowledged: bool = True, note: str = "") -> None:
    w = next((w for w in project.warnings if w.id == warning_id), None)
    if w is None:
        raise ReviewError(f"unknown warning {warning_id!r}")
    if acknowledged and not note.strip():
        raise ReviewError("say why this is intentional (a note is required to acknowledge a warning)")
    w.acknowledged, w.ack_note = acknowledged, note.strip() if acknowledged else ""
    if not acknowledged:
        project.reopen()


# ---- approval -----------------------------------------------------------------------------------------------
def blockers(project: Project, what: str) -> list[str]:
    """Everything standing between the user and approving `what`. Empty means approvable."""
    out: list[str] = []
    plan = project.plan
    if what not in ("characters", "costumes", "plan"):
        raise ReviewError("approve one of: characters, costumes, plan")
    if project.status not in (ProjectStatus.PLAN_READY,):
        out.append(f"project is {project.status.value}; approval happens at plan_ready")
        return out
    if plan is None or plan.entities is None:
        return ["there is no adaptation plan yet"]
    if not project.continuity_checked:
        out.append("the continuity check has not been run")
    problems = plan.problems
    if project.selection is not None:  # recomputed now, so a stale stored list can never block (or wrongly unblock) approval
        problems = all_problems(project, load_pack(project.selection.pack_id),
                                load_scripts()[project.selection.output_script])
    if what == "characters":
        out += [p for p in problems if "CHAR_" in p]
        out += [f"{c.id} has no plan entry" for c in project.characters
                if not any(e.character_id == c.id for e in plan.entities.characters)]
    elif what == "costumes":
        out += [p for p in problems if "COST_" in p]
        planned = {e.costume_id: e for e in plan.entities.costumes}
        out += [f"{c.id} has no plan entry" for c in project.costumes if c.id not in planned]
        for w in project.warnings:
            if w.code == "COSTUME_CHANGE_NO_REASON" and not w.acknowledged:
                new_id = _costume_after_change(project, w)
                if not (new_id and planned.get(new_id) and planned[new_id].change_reason.strip()):
                    out.append(f"unexplained costume change ({w.message}): add a reason to the plan or acknowledge the warning")
    else:
        out += list(problems)
        out += [f"scene {s} was planned before a later edit: re-plan it" for s in plan.stale_scenes]
        out += [f"{s.scene_id} has no plan" for s in project.scenes if s.scene_id not in plan.scenes]
        for d in project.decisions:
            if d.status == ReviewStatus.PROPOSED:
                out.append(f"{d.id} has not been reviewed")
    return out


def _costume_after_change(project: Project, warning) -> str | None:
    """The costume that starts at the end of a COSTUME_CHANGE warning's scene span."""
    if not warning.entity_id or not warning.affected_scene_ids:
        return None
    last = next((s for s in project.scenes if s.scene_id == warning.affected_scene_ids[-1]), None)
    return last.costumes.get(warning.entity_id) if last else None


def approve(project: Project, what: str) -> dict:
    """Approve characters | costumes | plan. Raises GateError listing the blockers if any."""
    found = blockers(project, what)
    if found:
        raise GateError(f"cannot approve {what}: " + "; ".join(found))
    setattr(project.approval, what, True)
    return try_finalize(project)


def try_finalize(project: Project) -> dict:
    """If all three approvals are given and no continuity error is unresolved, approve the project and
    apply the plan. Safe to call again, e.g. after acknowledging a warning."""
    if project.status in PAST_PLAN:
        return {"approved": True, "status": project.status.value, "waiting_for": []}
    if not project.approval.complete:
        missing = [k for k, v in project.approval.model_dump().items() if not v]
        return {"approved": False, "status": project.status.value, "waiting_for": missing}
    try:
        project.approve()  # needs continuity checked and no unresolved ERROR warning
    except GateError as e:
        return {"approved": False, "status": project.status.value, "waiting_for": [], "blocked_by": str(e)}
    apply_plan_to_records(project)
    # An earlier rewrite described an earlier plan. Clear it; unchanged scenes come back free from the cache.
    project.adapted_scenes, project.rewrite_failed = [], {}
    return {"approved": True, "status": project.status.value, "waiting_for": []}


def unapprove(project: Project, what: str | None = None) -> None:
    if what is None:
        project.reopen()
        return
    if what not in ("characters", "costumes", "plan"):
        raise ReviewError("unapprove one of: characters, costumes, plan (or none, for all)")
    kept = project.approval.model_copy()
    if project.status in PAST_PLAN:
        project.reopen()  # steps back to plan_ready; the other approvals still stand
    project.approval = kept
    setattr(project.approval, what, False)


def apply_plan_to_records(project: Project) -> None:
    """Copy the approved plan onto the canonical records. Source-side fields are kept, adapted ones added,
    so this is idempotent and reversible."""
    ent = project.plan.entities
    for cp in ent.characters:
        c = next(x for x in project.characters if x.id == cp.character_id)
        c.adapted_name, c.adapted_name_native = cp.name_roman, cp.name_native
        c.role_adapted, c.speech_register, c.address_terms = cp.role_adapted, cp.speech_register, list(cp.address_terms)
        c.physical_description, c.grooming = cp.appearance, cp.grooming
        c.approved = True
    for kp in ent.costumes:
        c = next(x for x in project.costumes if x.id == kp.costume_id)
        if c.source_garments is None:  # capture the source wording exactly once, even if it was empty
            c.source_garments = c.garments
        c.garments, c.fabrics, c.colours = kp.garments, kp.fabrics, kp.colours
        c.footwear, c.jewellery, c.headwear, c.grooming = kp.footwear, kp.jewellery, kp.headwear, kp.grooming
        c.change_reason = c.change_reason or kp.change_reason
        c.approved = True
    for lp in ent.locations:
        loc = next(x for x in project.locations if x.id == lp.location_id)
        loc.adapted_name, loc.adapted_name_native, loc.description = lp.name_roman, lp.name_native, lp.description
    for pp in ent.props:
        pr = next(x for x in project.props if x.id == pp.prop_id)
        pr.adapted_name, pr.adapted_name_native = pp.name_roman, pp.name_native
        pr.description = pp.description or pr.description
