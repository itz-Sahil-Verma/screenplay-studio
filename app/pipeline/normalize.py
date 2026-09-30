"""Step 5: raw per-scene extraction -> canonical registry (characters, locations, props,
costumes, scenes), each with one stable ID that every scene refers to.

Division of labour:
  * CODE does the deterministic work: case-insensitive matching, alias linking from the
    names the model reported, ID assignment, costume carry-forward, event de-duplication.
  * The LLM only PROPOSES extra merges the code cannot see (e.g. "Ma" and "Meera").
    Code validates every proposal and rejects unsafe ones (e.g. two people who appear
    together in a scene can never be merged). If the model call fails, normalization still
    completes deterministically.
Every decision is written to project.normalization_log for the review screen.
"""
import logging
import re
from collections import Counter

from pydantic import BaseModel, Field

from app.config import settings
from app.llm.base import LLMClient, try_parse
from app.models import (
    Character,
    Costume,
    IntExt,
    Location,
    ProductionElements,
    Project,
    ProjectStatus,
    Prop,
    Scene,
    StateChange,
    StateChangeKind,
)
from app.storage import JsonCache, default_cache, make_key

log = logging.getLogger(__name__)

_ARTICLES = ("the ", "a ", "an ")


# ---- text helpers -------------------------------------------------------------
def norm_key(s: str) -> str:
    """Case/punctuation-insensitive identity key: 'R. Kumar' == 'r kumar'; 'The Elder Son' == 'elder son'."""
    k = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()
    for art in _ARTICLES:
        if k.startswith(art):
            k = k[len(art):]
    return k


def fold_plural(k: str) -> str:
    """'cups' -> 'cup' (props/locations only)."""
    return re.sub(r"(?:es|s)$", "", k) if len(k) > 3 else k


def display(name: str) -> str:
    """'RAVI' -> 'Ravi', 'R. KUMAR' -> 'R. Kumar'; mixed case is left as written."""
    name = name.strip()
    return name.title() if name.isupper() else name


def display_lower(name: str) -> str:
    """'LETTER' -> 'letter' (things, not people)."""
    name = name.strip()
    return name.lower() if name.isupper() else name


def display_place(name: str) -> str:
    """'FAMILY HOME' -> 'Family home'; 'Dusty road' stays as written."""
    name = name.strip()
    if name.isupper():
        name = name.lower()
    return name[:1].upper() + name[1:]


def slug(s: str) -> str:
    return re.sub(r"\W+", "_", s.upper()).strip("_") or "X"


def unique_id(base: str, used: set[str]) -> str:
    cand, n = base, 2
    while cand in used:
        cand, n = f"{base}_{n}", n + 1
    used.add(cand)
    return cand


def scene_id(number: int) -> str:
    return f"SC{number:02d}"


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ---- LLM merge proposal -------------------------------------------------------
class MergeGroup(BaseModel):
    ids: list[str]  # candidate labels that are the SAME thing, e.g. ["C1", "C4"]
    reason: str = ""


class MergeProposal(BaseModel):
    characters: list[MergeGroup] = Field(default_factory=list)
    locations: list[MergeGroup] = Field(default_factory=list)
    props: list[MergeGroup] = Field(default_factory=list)
    costumes: list[MergeGroup] = Field(default_factory=list)


MERGE_SYSTEM = """You review candidate entities that were extracted from separate scenes of one screenplay.
Decide which candidates are really the SAME character, location, prop or costume.

Rules:
- Merge only when you are confident. If unsure, do not merge.
- Two characters that appear TOGETHER in the same scene are different people: never merge them.
- Do not merge on a similar role alone (two different servants, two different neighbours).
- Costume candidates belong to one character each; merge only descriptions of the SAME garment
  (e.g. "red shirt" and "red checked shirt"). Different garments (a blue jacket vs a red shirt)
  are a costume CHANGE and must NOT be merged.
- Use only the labels given. Each label may appear in at most one group. Return empty lists if
  nothing should be merged. Output JSON for the given schema only."""


def _validate_groups(groups: list[MergeGroup], labels: dict[str, set[int]], kind: str, notes: list[str],
                     forbid_cooccurrence: bool) -> list[list[str]]:
    """Keep only safe groups. `labels` maps a candidate label to the scene numbers it appears in."""
    used: set[str] = set()
    accepted: list[list[str]] = []
    for g in groups:
        ids = list(dict.fromkeys(g.ids))
        if len(ids) < 2:
            continue
        unknown = [i for i in ids if i not in labels]
        if unknown:
            notes.append(f"REJECTED model merge of {kind} {ids}: unknown label(s) {unknown}")
            continue
        if any(i in used for i in ids):
            notes.append(f"REJECTED model merge of {kind} {ids}: a label is already in another group")
            continue
        if forbid_cooccurrence:
            clash = sorted({n for x in range(len(ids)) for y in range(x + 1, len(ids))
                            for n in labels[ids[x]] & labels[ids[y]]})
            if clash:
                notes.append(
                    f"REJECTED model merge of {kind} {ids}: they appear together in scene(s) {clash}, "
                    "so they are different"
                )
                continue
        accepted.append(ids)
        used.update(ids)
    return accepted


# ---- scene heading -> INT/EXT ---------------------------------------------------
_HEAD = re.compile(r"^\s*(?:\d+[.)]?\s+)?(INT\.?/EXT\.?|EXT\.?/INT\.?|I/E\.?|INT\.?|EXT\.?)(?=[\s.])")


def int_ext_of(heading: str, model_value: str) -> tuple[IntExt, str]:
    """Heading text is authoritative (code-derived); the model's value is only a fallback."""
    m = _HEAD.match(heading or "")
    token = (m.group(1) if m else model_value or "").upper().replace(".", "").replace(" ", "")
    if token in ("INT/EXT", "EXT/INT", "I/E"):
        return IntExt.INT_EXT, ""
    if token == "INT":
        return IntExt.INT, ""
    if token == "EXT":
        return IntExt.EXT, ""
    return IntExt.INT, "no INT/EXT found in heading or extraction; defaulted to INT"


# ---- main ---------------------------------------------------------------------
def normalize(project: Project, client: LLMClient | None = None, cache: JsonCache | None = None,
              force: bool = False) -> Project:
    """Rebuild the canonical registry from the raw extractions. Idempotent: safe to re-run.
    Refuses if a person has edited the records (it would silently undo their work) unless force=True."""
    if project.user_edits and not force:
        raise ValueError(f"the records have {len(project.user_edits)} manual edit(s); re-normalizing would discard "
                         "them. Pass force=True to start over.")
    if force:
        project.user_edits = []
    if project.status not in (ProjectStatus.EXTRACTED, ProjectStatus.NORMALIZED):
        raise ValueError(f"normalize needs an extracted project, not {project.status.value}")
    missing = [s.number for s in project.source_scenes if s.extraction is None]
    if not project.source_scenes or missing:
        raise ValueError(f"scene(s) {missing or 'all'} have no extraction; run extraction first")

    notes: list[str] = []
    scenes = sorted(project.source_scenes, key=lambda s: s.number)

    # 1. deterministic character clusters: union names with the aliases the model reported
    uf = UnionFind()
    entries: list[tuple[int, object]] = []  # (scene number, MentionedCharacter)
    for sc in scenes:
        for m in sc.extraction.characters:
            k = norm_key(m.name)
            if not k:
                notes.append(f"scene {sc.number}: a character with an empty name was ignored")
                continue
            entries.append((sc.number, m))
            uf.add(k)
            for alias in m.other_names:
                ak = norm_key(alias)
                if ak:
                    uf.union(k, ak)

    def char_root(m) -> str:
        return uf.find(norm_key(m.name))

    char_roots: list[str] = []
    for _, m in entries:
        r = char_root(m)
        if r not in char_roots:
            char_roots.append(r)

    def scenes_of_root(root: str) -> set[int]:
        return {n for n, m in entries if char_root(m) == root}

    # 2. deterministic location and prop clusters
    def loc_key(name: str) -> str:
        return fold_plural(norm_key(name))

    loc_keys: list[str] = []
    for sc in scenes:
        k = loc_key(sc.extraction.location)
        if not k:
            notes.append(f"scene {sc.number}: no location extracted")
        elif k not in loc_keys:
            loc_keys.append(k)

    prop_keys: list[str] = []
    for sc in scenes:
        for p in sc.extraction.props:
            k = fold_plural(norm_key(p.name))
            if k and k not in prop_keys:
                prop_keys.append(k)

    # 3. costume candidates: characters with 2+ distinct descriptions
    costume_cands: list[tuple[str, str]] = []  # (char root, description key)
    for root in char_roots:
        seen: list[str] = []
        for n, m in entries:
            if char_root(m) == root and m.costume.strip():
                ck = norm_key(m.costume)
                if ck not in seen:
                    seen.append(ck)
        if len(seen) >= 2:
            costume_cands.extend((root, ck) for ck in seen)

    # 4. ONE model call proposing extra merges (skipped when nothing could be merged)
    label_c = {f"C{i + 1}": root for i, root in enumerate(char_roots)}
    label_name = {lab: display(_first_name(entries, char_root, root)) for lab, root in label_c.items()}  # before any merge
    label_l = {f"L{i + 1}": k for i, k in enumerate(loc_keys)}
    label_p = {f"P{i + 1}": k for i, k in enumerate(prop_keys)}
    label_k = {f"K{i + 1}": rc for i, rc in enumerate(costume_cands)}
    proposal = MergeProposal()
    if client is not None and (len(label_c) > 1 or len(label_l) > 1 or len(label_p) > 1 or len(label_k) > 1):
        proposal = _propose_merges(client, cache or default_cache("normalize"), scenes, entries, char_root,
                                   label_c, label_l, label_p, label_k, notes)

    # 5. validate and apply merges
    c_scenes = {lab: scenes_of_root(root) for lab, root in label_c.items()}
    for ids in _validate_groups(proposal.characters, c_scenes, "characters", notes, True):
        for i in ids[1:]:
            uf.union(label_c[ids[0]], label_c[i])
        names = [label_name[i] for i in ids]
        reason = next(g.reason for g in proposal.characters if ids[0] in g.ids)
        notes.append(f"MERGED characters {names} (proposed by model: {reason})")

    loc_scenes = {lab: {sc.number for sc in scenes if loc_key(sc.extraction.location) == k} for lab, k in label_l.items()}
    loc_uf = UnionFind()
    for k in loc_keys:
        loc_uf.add(k)
    for ids in _validate_groups(proposal.locations, loc_scenes, "locations", notes, True):
        for i in ids[1:]:
            loc_uf.union(label_l[ids[0]], label_l[i])
        notes.append(f"MERGED locations {[label_l[i] for i in ids]} (proposed by model)")

    prop_scenes = {lab: {sc.number for sc in scenes if any(fold_plural(norm_key(p.name)) == k for p in sc.extraction.props)}
                   for lab, k in label_p.items()}
    prop_uf = UnionFind()
    for k in prop_keys:
        prop_uf.add(k)
    for ids in _validate_groups(proposal.props, prop_scenes, "props", notes, True):
        for i in ids[1:]:
            prop_uf.union(label_p[ids[0]], label_p[i])
        notes.append(f"MERGED props {[label_p[i] for i in ids]} (proposed by model)")

    # (character roots may have changed after merges: recompute the final mapping)
    final_roots: list[str] = []
    for _, m in entries:
        r = char_root(m)
        if r not in final_roots:
            final_roots.append(r)

    cost_uf = UnionFind()
    k_scenes = {lab: {n for n, m in entries if char_root(m) == uf.find(rc[0]) and norm_key(m.costume) == rc[1]}
                for lab, rc in label_k.items()}
    valid_costume_groups = []
    for ids in _validate_groups(proposal.costumes, k_scenes, "costumes", notes, False):
        if len({uf.find(label_k[i][0]) for i in ids}) != 1:
            notes.append(f"REJECTED model merge of costumes {ids}: they belong to different characters")
            continue
        valid_costume_groups.append(ids)
    for ids in valid_costume_groups:
        for i in ids[1:]:
            cost_uf.union(label_k[ids[0]][1], label_k[i][1])
        notes.append(f"MERGED costume descriptions {[label_k[i][1] for i in ids]} (proposed by model)")

    # 6. build characters
    used_ids: set[str] = set()
    characters: list[Character] = []
    char_id_of_root: dict[str, str] = {}
    char_index: dict[str, str] = {}  # every known name/alias key -> char id
    for root in final_roots:
        mine = [(n, m) for n, m in entries if char_root(m) == root]
        names = [m.name for _, m in mine]
        by_key = Counter(norm_key(n) for n in names)
        best_key = by_key.most_common(1)[0][0]
        raw_for_best = next(n for n in names if norm_key(n) == best_key)
        variants = [n for n in names if norm_key(n) == best_key]
        canonical = next((v for v in variants if not v.isupper()), display(raw_for_best)).strip()
        cid = unique_id("CHAR_" + slug(canonical), used_ids)
        char_id_of_root[root] = cid

        aliases: list[str] = []
        seen_keys = {norm_key(canonical)}
        for _, m in mine:
            for a in [m.name, *m.other_names]:
                ak = norm_key(a)
                if ak and ak not in seen_keys:
                    seen_keys.add(ak)
                    aliases.append(display(a))
        for a in [canonical, *aliases]:
            char_index[norm_key(a)] = cid

        age = next((int(x.group()) for _, m in mine if (x := re.search(r"\d+", m.age))), None)
        roles = [m.role.strip() for _, m in mine if m.role.strip()]
        rel_notes = list(dict.fromkeys(r.strip() for _, m in mine for r in m.relationships if r.strip()))
        pers = list(dict.fromkeys(m.personality.strip() for _, m in mine if m.personality.strip()))
        emo = [m.emotional_state.strip() for _, m in mine if m.emotional_state.strip()]
        characters.append(Character(
            id=cid, name=canonical, aliases=aliases, age=age,
            role=Counter(roles).most_common(1)[0][0] if roles else "",
            relationship_notes=rel_notes, personality="; ".join(pers),
            emotional_state=emo[-1] if emo else "",
            scene_ids=[scene_id(n) for n in sorted({n for n, _ in mine})],
        ))
        if len(set(norm_key(n) for n in names)) > 1 or aliases:
            notes.append(f"{cid}: merged names/aliases {[canonical, *aliases]}")

    # 7. locations
    used_loc: set[str] = set()
    locations: list[Location] = []
    loc_id_of_key: dict[str, str] = {}
    for root in dict.fromkeys(loc_uf.find(k) for k in loc_keys):
        members = [k for k in loc_keys if loc_uf.find(k) == root]
        raw = [sc.extraction.location.strip() for sc in scenes
               if loc_key(sc.extraction.location) in members and sc.extraction.location.strip()]
        name = display_place(Counter(raw).most_common(1)[0][0])
        lid = unique_id("LOC_" + slug(name), used_loc)
        for k in members:
            loc_id_of_key[k] = lid
        subs: list[str] = []
        for sc in scenes:
            if loc_key(sc.extraction.location) in members and sc.extraction.sub_location.strip():
                if norm_key(sc.extraction.sub_location) not in [norm_key(s) for s in subs]:
                    subs.append(display_place(sc.extraction.sub_location))
        locations.append(Location(id=lid, name=name, sub_locations=subs))

    # 8. props
    used_prop: set[str] = set()
    props: list[Prop] = []
    prop_id_of_key: dict[str, str] = {}
    for root in dict.fromkeys(prop_uf.find(k) for k in prop_keys):
        members = [k for k in prop_keys if prop_uf.find(k) == root]
        raw, desc = [], []
        for sc in scenes:
            for p in sc.extraction.props:
                if fold_plural(norm_key(p.name)) in members:
                    raw.append(p.name.strip())
                    if p.description.strip():
                        desc.append(p.description.strip())
        name = display_lower(Counter(raw).most_common(1)[0][0])
        pid = unique_id("PROP_" + slug(name), used_prop)
        for k in members:
            prop_id_of_key[k] = pid
        aliases = [display_lower(a) for a in dict.fromkeys(raw) if norm_key(a) != norm_key(name)]
        props.append(Prop(id=pid, name=name, aliases=aliases, description=desc[0] if desc else ""))

    def prop_id(name: str) -> str | None:
        nk = norm_key(name)
        exact = prop_id_of_key.get(fold_plural(nk))
        if exact:
            return exact
        # "cup of tea", "handkerchief tied around his palm": find a known prop named inside the text.
        # Longest name wins; on a tie, the one mentioned first.
        found = []
        for pk, pid in prop_id_of_key.items():
            m = re.search(rf"(?<!\w){re.escape(pk)}(?:s|es)?(?!\w)", nk)
            if m:
                found.append((-len(pk), m.start(), pid))
        return min(found)[2] if found else None

    def resolve_char(name: str) -> str | None:
        return char_index.get(norm_key(name))

    def resolve_holder(raw: str) -> str:
        if not raw.strip():
            return ""
        return resolve_char(raw) or f"@{raw.strip().lower()}"

    # 9. costumes: carry forward until the story changes them
    costumes: list[Costume] = []
    costume_of: dict[tuple[str, int], str] = {}  # (char id, scene number) -> costume id
    for root in final_roots:
        cid = char_id_of_root[root]
        cname = next(c.name for c in characters if c.id == cid)
        in_scene: dict[int, str] = {}
        for n, m in entries:
            if char_root(m) == root and n not in in_scene:
                in_scene[n] = ""
            if char_root(m) == root and m.costume.strip() and not in_scene[n]:
                in_scene[n] = m.costume.strip()
        first_desc = next((d for _, d in sorted(in_scene.items()) if d), "")
        created: dict[str, Costume] = {}

        def costume_for(desc_key: str, raw_desc: str) -> Costume:
            if desc_key not in created:
                idx = len(created) + 1
                costume = Costume(id=f"COST_{cid[5:]}_{idx:02d}", character_id=cid, garments=display_lower(raw_desc))
                created[desc_key] = costume
                costumes.append(costume)
            return created[desc_key]

        if first_desc:
            cur = costume_for(cost_uf.find(norm_key(first_desc)), first_desc)
        else:
            cur = costume_for("", "")
            notes.append(f"{cid} ({cname}): no costume described in the source; a placeholder "
                         f"{cur.id} was created (the adaptation plan will define it)")
        for n in sorted(in_scene):
            desc = in_scene[n]
            if desc:
                dk = cost_uf.find(norm_key(desc))
                new = costume_for(dk, desc)
                if new.id != cur.id:
                    sc_events = next(s for s in scenes if s.number == n).extraction.events
                    reason = next((e.note.strip() for e in sc_events if e.kind == "costume_change"
                                   and norm_key(e.character) in {norm_key(cname)} | {k for k, v in char_index.items() if v == cid}
                                   and e.note.strip()), "")
                    new.change_reason = reason
                    cur = new
            costume_of[(cid, n)] = cur.id
            if scene_id(n) not in cur.scene_ids:
                cur.scene_ids.append(scene_id(n))
        if len(created) > 1:
            notes.append(f"{cid} ({cname}) has {len(created)} costumes: " + ", ".join(
                f"{c.id}={c.garments!r} in {c.scene_ids}" + ("" if c.change_reason else " [no story reason given for the change]")
                for c in created.values()))

    # 10. scene records
    out_scenes: list[Scene] = []
    mentioned_by_scene: dict[int, list[str]] = {}
    prop_ids = {p.id for p in props}
    for sc in scenes:
        ex = sc.extraction
        n = sc.number
        ie, warn = int_ext_of(sc.heading, ex.int_ext)
        if warn:
            notes.append(f"scene {n}: {warn}")
        present: list[str] = []
        entrances: list[str] = []
        exits: list[str] = []
        for m in ex.characters:
            cid_ = resolve_char(m.name)
            if not cid_:
                continue
            if cid_ not in present:
                present.append(cid_)
            if m.enters and cid_ not in entrances:
                entrances.append(cid_)
            if m.exits and cid_ not in exits:
                exits.append(cid_)

        holders_start: dict[str, str] = {}
        holders_end: dict[str, str] = {}
        mentioned: list[str] = []
        for p in ex.props:
            pid = prop_id(p.name)
            if not pid:
                continue
            if pid not in mentioned:
                mentioned.append(pid)
            if p.holder_at_start.strip():
                holders_start[pid] = resolve_holder(p.holder_at_start)
            if p.holder_at_end.strip():
                holders_end[pid] = resolve_holder(p.holder_at_end)

        changes: list[StateChange] = []
        for ev in ex.events:
            try:
                kind = StateChangeKind(ev.kind)
            except ValueError:
                notes.append(f"scene {n}: event kind {ev.kind!r} is not valid; event skipped")
                continue
            who = resolve_char(ev.character)
            if not who:
                notes.append(f"scene {n}: event {ev.kind} refers to unknown character {ev.character!r}; skipped")
                continue
            item = ev.item.strip()
            if kind in (StateChangeKind.PROP_GAIN, StateChangeKind.PROP_LOSS, StateChangeKind.PROP_TRANSFER):
                item = prop_id(item) or item
            to = resolve_char(ev.to_character) if ev.to_character.strip() else None
            changes.append(StateChange(kind=kind, character_id=who, item=item, to_character_id=to, note=ev.note.strip()))
        changes = _dedupe_events(changes)
        for c in changes:  # a prop that only appears in an event still counts as present
            if c.item in prop_ids and c.item not in mentioned:
                mentioned.append(c.item)
        mentioned_by_scene[n] = mentioned
        # present at the start: held by someone, or a set piece nobody is recorded holding
        static = [pid for pid in mentioned if pid not in holders_start and pid not in holders_end]

        pe = ProductionElements(
            set_dressing=ex.set_dressing, food=ex.food, vehicles=ex.vehicles, animals=ex.animals,
            extras=ex.extras, rituals=ex.rituals, gestures=ex.gestures, sound_music=ex.sound_music,
        )
        out_scenes.append(Scene(
            scene_id=scene_id(n), number=n, int_ext=ie,
            location_id=loc_id_of_key.get(loc_key(ex.location), ""),
            sub_location=ex.sub_location.strip(), time=ex.time.strip(), day=ex.day.strip(),
            weather=ex.weather.strip(), mood=ex.mood.strip(), summary=ex.summary.strip(),
            dramatic_purpose=ex.dramatic_purpose.strip(), emotional_change=ex.emotional_change.strip(),
            source_text=sc.text, characters=present, entrances=entrances, exits=exits,
            costumes={c: costume_of[(c, n)] for c in present if (c, n) in costume_of},
            props_in=list(holders_start) + static, props_out=[p for p, h in holders_end.items() if not h.startswith("@")],
            prop_holder_start=holders_start, prop_holder_end=holders_end,
            state_changes=changes, production=pe,
        ))

    # 11. back-links (which scenes each record appears in)
    for loc in locations:
        loc.scene_ids = [s.scene_id for s in out_scenes if s.location_id == loc.id]
    for pr in props:
        pr.scene_ids = [s.scene_id for s in out_scenes if pr.id in mentioned_by_scene[s.number]]

    project.characters, project.locations, project.props = characters, locations, props
    project.costumes, project.scenes = costumes, out_scenes
    project.normalization_log = notes
    project.continuity_checked = False  # records changed: the check must be re-run
    if project.status == ProjectStatus.EXTRACTED:
        project.transition(ProjectStatus.NORMALIZED)
    log.info("normalized: %d characters, %d locations, %d props, %d costumes",
             len(characters), len(locations), len(props), len(costumes))
    return project


def _first_name(entries, char_root, root: str) -> str:
    return next(m.name for _, m in entries if char_root(m) == root)


def _dedupe_events(changes: list[StateChange]) -> list[StateChange]:
    """Drop exact duplicates, and the gain/loss that a prop_transfer already implies."""
    seen, out = set(), []
    for c in changes:
        key = (c.kind, c.character_id, c.item.lower(), c.to_character_id)
        if key not in seen:
            seen.add(key)
            out.append(c)
    implied = set()
    for c in out:
        if c.kind == StateChangeKind.PROP_TRANSFER and c.to_character_id:
            implied.add((StateChangeKind.PROP_LOSS, c.character_id, c.item.lower()))
            implied.add((StateChangeKind.PROP_GAIN, c.to_character_id, c.item.lower()))
    return [c for c in out if (c.kind, c.character_id, c.item.lower()) not in implied
            or c.kind == StateChangeKind.PROP_TRANSFER]


def _propose_merges(client, cache, scenes, entries, char_root, label_c, label_l, label_p, label_k, notes) -> MergeProposal:
    """Ask the model for extra merges. Never raises: on failure normalization continues without it."""
    lines = ["CHARACTERS"]
    for lab, root in label_c.items():
        mine = [(n, m) for n, m in entries if char_root(m) == root]
        names = list(dict.fromkeys(x for _, m in mine for x in [m.name, *m.other_names]))
        roles = list(dict.fromkeys(m.role for _, m in mine if m.role))
        rels = list(dict.fromkeys(r for _, m in mine for r in m.relationships))
        lines.append(f"{lab}: names={names}; roles={roles}; relationships={rels}; scenes={sorted({n for n, _ in mine})}")
    lines.append("\nLOCATIONS")
    for lab, k in label_l.items():
        ns = [sc.number for sc in scenes if fold_plural(norm_key(sc.extraction.location)) == k]
        names = list(dict.fromkeys(sc.extraction.location for sc in scenes if fold_plural(norm_key(sc.extraction.location)) == k))
        lines.append(f"{lab}: names={names}; scenes={ns}")
    lines.append("\nPROPS")
    for lab, k in label_p.items():
        found = [(sc.number, p) for sc in scenes for p in sc.extraction.props if fold_plural(norm_key(p.name)) == k]
        lines.append(f"{lab}: names={list(dict.fromkeys(p.name for _, p in found))}; "
                     f"descriptions={list(dict.fromkeys(p.description for _, p in found if p.description))}; "
                     f"scenes={sorted({n for n, _ in found})}")
    if label_k:
        lines.append("\nCOSTUMES (per character)")
        for lab, (root, ck) in label_k.items():
            who = display(_first_name(entries, char_root, root))
            sc_list = sorted({n for n, m in entries if char_root(m) == root and norm_key(m.costume) == ck})
            lines.append(f"{lab}: character={who}; description={ck!r}; scenes={sc_list}")
    prompt = "\n".join(lines)

    key = make_key(MERGE_SYSTEM, prompt, f"{client.name}:{getattr(client, 'deployment', None) or getattr(client, 'model', '')}")
    hit = cache.get(key)
    if hit is not None:
        return MergeProposal.model_validate(hit)
    feedback = ""
    for _ in range(settings.llm_max_retries):
        try:
            raw = client.complete_json(MERGE_SYSTEM, prompt + feedback, MergeProposal)
        except Exception as e:  # noqa: BLE001: a proposal is optional
            notes.append(f"model merge proposal unavailable ({type(e).__name__}); used deterministic matching only")
            return MergeProposal()
        obj, err = try_parse(raw, MergeProposal)
        if obj is not None:
            cache.set(key, obj.model_dump(mode="json"))
            return obj
        feedback = f"\n\nYour previous answer did not match the schema:\n{err}\nReturn corrected JSON only."
    notes.append("model merge proposal was not valid JSON; used deterministic matching only")
    return MergeProposal()
