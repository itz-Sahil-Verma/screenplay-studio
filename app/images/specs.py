"""Turns the APPROVED records into image specifications, deterministically.

A spec is a structured dict; the prompt is derived from it, and the spec's hash identifies exactly what the image was
made from. A spec includes the hashes of the reference images it depends on, so a change anywhere upstream (a
character's appearance, a costume, a reference image) changes the hash of everything downstream and nothing else. That
one property gives "regenerate only what is affected" for images.

The rule that prevents duplicates: one image per unique appearance. A character's first costume IS the character
reference image, so it never gets a second sheet.
"""
from app.models import Asset, AssetKind, AssetStatus, Character, Costume, CulturePack, Project, Scene, spec_hash

STYLE = "photorealistic cinematic film still, natural light, muted realistic colour grade, 35mm lens, no text, no captions, no watermark"
PORTRAIT, LANDSCAPE = "1024x1536", "1536x1024"
MAX_REFERENCES = 4  # reference images sent with one keyframe; further characters are described in words


def _costume_fields(k: Costume) -> dict:
    return {f: getattr(k, f) for f in ("garments", "fabrics", "colours", "footwear", "jewellery", "headwear", "grooming") if getattr(k, f)}


def _culture_line(project: Project, pack: CulturePack) -> str:
    s = project.selection
    return f"{pack.culture} culture, {s.region}, {s.setting.value} setting"


def first_costume(project: Project, char_id: str) -> Costume | None:
    return next((k for k in project.costumes if k.character_id == char_id), None)


def char_ref_id(char_id: str) -> str:
    return f"ASSET_CHARREF_{char_id}"


def costume_asset_id(project: Project, costume: Costume) -> str:
    """The image that shows this costume on its character: the character reference for the first costume, else its own sheet."""
    first = first_costume(project, costume.character_id)
    return char_ref_id(costume.character_id) if first and first.id == costume.id else f"ASSET_COSTUME_{costume.id}"


def _join(parts: list[tuple[str, str]]) -> str:
    return " ".join(f"{label}: {value}." for label, value in parts if value)


def spec_prompt(spec: dict) -> str:
    """The prompt, derived from the spec alone (so the stored spec is enough to reproduce the image)."""
    kind = spec["kind"]
    if kind == "character_ref":
        w, c = spec["who"], spec["costume"]
        return (
            "Full-body character reference image, head to toe, standing in a neutral relaxed pose facing the camera, plain light-grey studio "
            "background, soft even lighting. "
            + _join([("Subject", f"{w['name']}, {w['age'] or ''} {w['role']}, {spec['culture']}".replace("  ", " ")), ("Appearance", w["appearance"]), ("Grooming", w["grooming"]),
                     ("Wearing", c.get("garments", "")), ("Fabrics", c.get("fabrics", "")), ("Colours", c.get("colours", "")), ("Footwear", c.get("footwear", "")),
                     ("Jewellery", c.get("jewellery", "")), ("Headwear", c.get("headwear", ""))])
            + f" Style: {spec['style']}."
        )
    if kind == "costume_sheet":
        c = spec["costume"]
        return (
            "The reference image shows a person. Create a NEW full-body image of exactly the same person (identical face, age, body, hair and facial hair), "
            "standing in a neutral pose facing the camera on a plain light-grey studio background, now wearing this costume. "
            + _join([("Wearing", c.get("garments", "")), ("Fabrics", c.get("fabrics", "")), ("Colours", c.get("colours", "")), ("Footwear", c.get("footwear", "")),
                     ("Jewellery", c.get("jewellery", "")), ("Headwear", c.get("headwear", "")), ("Grooming", c.get("grooming", ""))])
            + f" Style: {spec['style']}."
        )
    who = "; ".join(
        f"reference image {p['image']} is {p['name']} ({p['role']}), wearing {p['wearing']}" for p in spec["pictured"]
    )
    others = ("; also in the scene but not pictured in a reference: " + ", ".join(f"{o['name']} ({o['role']})" for o in spec["others"])) if spec["others"] else ""
    return (
        "Cinematic keyframe for a film scene, wide establishing composition. "
        + _join([("Place", f"{spec['place']['name']}. {spec['place']['description']}"), ("Time and light", f"{spec['time']}. {spec['atmosphere']}".strip(". ")),
                 ("Action", spec["blocking"]), ("Props visible", spec["props"]), ("Culture", spec["culture"])])
        + f" Characters, each must look IDENTICAL to their reference image: {who}{others}. Style: {spec['style']}."
    )


def _blocking(project: Project, scene: Scene) -> str:
    adapted = next((a for a in project.adapted_scenes if a.source_scene_id == scene.scene_id), None)
    lines = [l.gloss for l in adapted.lines if l.kind.value in ("action", "gesture") and l.gloss][:2] if adapted else []
    if not lines and project.plan and scene.scene_id in project.plan.scenes:
        lines = project.plan.scenes[scene.scene_id].gestures[:2]
    return " ".join(lines)


def _asset(kind: AssetKind, aid: str, entity: str, spec: dict, refs: list[str]) -> Asset:
    return Asset(id=aid, kind=kind, entity_id=entity, spec=spec, spec_hash=spec_hash(spec), prompt=spec_prompt(spec),
                 reference_asset_ids=refs, size=spec["size"], status=AssetStatus.PENDING)


def desired_assets(project: Project, pack: CulturePack) -> list[Asset]:
    """Every image the approved records call for, in dependency order (references, then sheets, then keyframes)."""
    culture = _culture_line(project, pack)
    out: list[Asset] = []
    hashes: dict[str, str] = {}

    for c in project.characters:
        k = first_costume(project, c.id)
        spec = {"kind": "character_ref", "entity_id": c.id, "size": PORTRAIT, "style": STYLE, "culture": culture, "refs": [],
                "who": {"name": c.adapted_name or c.name, "age": c.age, "role": c.role_adapted or c.role, "appearance": c.physical_description, "grooming": c.grooming},
                "costume": _costume_fields(k) if k else {}}
        a = _asset(AssetKind.CHARACTER_REF, char_ref_id(c.id), c.id, spec, [])
        hashes[a.id] = a.spec_hash
        out.append(a)

    for k in project.costumes:
        aid = costume_asset_id(project, k)
        if aid == char_ref_id(k.character_id):
            continue  # the first costume is the character reference: one image per appearance
        ref = char_ref_id(k.character_id)
        spec = {"kind": "costume_sheet", "entity_id": k.id, "character_id": k.character_id, "size": PORTRAIT, "style": STYLE,
                "costume": _costume_fields(k), "refs": [{"asset": ref, "spec_hash": hashes[ref]}]}
        a = _asset(AssetKind.COSTUME_SHEET, aid, k.id, spec, [ref])
        hashes[a.id] = a.spec_hash
        out.append(a)

    locs = {l.id: l for l in project.locations}
    for s in sorted(project.scenes, key=lambda s: s.number):
        loc = locs.get(s.location_id)
        plan = project.plan.scenes.get(s.scene_id) if project.plan else None
        chars = [next(c for c in project.characters if c.id == cid) for cid in s.characters]
        pictured, others, refs = [], [], []
        for c in chars:
            k = next((x for x in project.costumes if x.id == s.costumes.get(c.id)), None)
            info = {"name": c.adapted_name or c.name, "role": c.role_adapted or c.role, "wearing": (k.garments if k else "") or "their everyday clothes"}
            if len(pictured) < MAX_REFERENCES and k:
                ref = costume_asset_id(project, k)
                pictured.append({**info, "image": len(pictured) + 1})
                refs.append(ref)
            else:
                others.append(info)
        spec = {"kind": "scene_keyframe", "entity_id": s.scene_id, "size": LANDSCAPE, "style": STYLE, "culture": culture,
                "place": {"name": (loc.adapted_name or loc.name) if loc else "", "description": loc.description if loc else ""},
                "time": s.time, "atmosphere": (plan.setting_notes if plan else "")[:260],
                "blocking": _blocking(project, s), "props": ", ".join(p.adapted_name or p.name for p in project.props if p.id in {*s.prop_holder_start, *s.prop_holder_end}),
                "pictured": pictured, "others": others, "refs": [{"asset": r, "spec_hash": hashes[r]} for r in refs]}
        out.append(_asset(AssetKind.SCENE_KEYFRAME, f"ASSET_KEYFRAME_{s.scene_id}", s.scene_id, spec, refs))
    return out
