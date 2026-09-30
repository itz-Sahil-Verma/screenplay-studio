"""The export package: the folder layout the brief asks for, built from the project's records. Pure code."""
import json
import re
import shutil
import zipfile
from pathlib import Path

from app.images.generate import asset_path
from app.models import AssetKind, AssetStatus, GateError, Project, ProjectStatus

from .pdf import adapted_screenplay_pdf, continuity_report_pdf


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "item"


def scene_breakdown(project: Project) -> dict:
    """Scenes, characters, props, costumes, states, continuity: every canonical record and where it came from."""
    return {
        "project": {"id": project.id, "source_file": project.source_filename,
                    "culture": project.selection.model_dump(mode="json") if project.selection else None},
        "scenes": [s.model_dump(mode="json") for s in project.scenes],
        "characters": [c.model_dump(mode="json") for c in project.characters],
        "locations": [x.model_dump(mode="json") for x in project.locations],
        "props": [x.model_dump(mode="json") for x in project.props],
        "costumes": [x.model_dump(mode="json") for x in project.costumes],
        "continuity_warnings": [w.model_dump(mode="json") for w in project.warnings],
        "adaptation_decisions": [d.model_dump(mode="json") for d in project.decisions],
        "normalization_log": project.normalization_log,
        "manual_edits": project.user_edits,
    }


def _dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _provenance(a) -> dict:
    """What reproduces the image: model, prompt, structured spec and the reference images it was conditioned on."""
    return {"asset": a.id, "model": a.model, "prompt": a.prompt, "spec": a.spec, "spec_hash": a.spec_hash,
            "references": a.reference_asset_ids, "attempts": a.attempts, "seconds": a.seconds}


def _write_bibles(project: Project, dest: Path) -> None:
    """One file per character and one per costume VARIANT, each with its full record. A character's first costume
    is shown by the character reference image itself (one image per unique appearance, never a duplicate), so its
    costume entry reuses that picture and says so, instead of looking missing."""
    assets = {a.id: a for a in project.assets}
    cost_of: dict[str, list] = {}
    for k in project.costumes:
        cost_of.setdefault(k.character_id, []).append(k)
    for c in project.characters:
        name = _slug(c.adapted_name or c.name)
        ref = assets.get(f"ASSET_CHARREF_{c.id}")
        if ref and asset_path(project, ref).exists():
            shutil.copy(asset_path(project, ref), dest / "character_bible" / f"{name}.png")
        _dump(dest / "character_bible" / f"{name}.json", {
            "character_id": c.id, "name": c.adapted_name or c.name, "name_native": c.adapted_name_native,
            "source_name": c.name, "aliases": c.aliases, "age": c.age, "role": c.role_adapted or c.role,
            "physical_description": c.physical_description, "grooming": c.grooming, "personality": c.personality,
            "speech_register": c.speech_register, "address_terms": c.address_terms, "scenes": c.scene_ids,
            "costumes": [k.id for k in cost_of.get(c.id, [])], "image": _provenance(ref) if ref else None})
    for k in project.costumes:
        c = project.character(k.character_id)
        name = f"{_slug((c.adapted_name or c.name) if c else k.character_id)}_{_slug(k.id)}"
        sheet = assets.get(f"ASSET_COSTUME_{k.id}")
        img = sheet or assets.get(f"ASSET_CHARREF_{k.character_id}")
        if img and asset_path(project, img).exists():
            shutil.copy(asset_path(project, img), dest / "costume_bible" / f"{name}.png")
        _dump(dest / "costume_bible" / f"{name}.json", {
            "costume_id": k.id, "character_id": k.character_id, "garments": k.garments, "source_garments": k.source_garments,
            "fabrics": k.fabrics, "colours": k.colours, "footwear": k.footwear, "jewellery": k.jewellery,
            "headwear": k.headwear, "grooming": k.grooming, "scenes": k.scene_ids, "change_reason": k.change_reason,
            "image_note": "own costume sheet" if sheet else "first look: this is the character reference image, not generated twice",
            "image": _provenance(img) if img else None})


def missing_for_export(project: Project) -> list[str]:
    out = []
    if not project.adapted_scenes:
        out.append("the adapted screenplay has not been written")
    bad = [a.id for a in project.assets if a.status != AssetStatus.GENERATED]
    if not project.assets:
        out.append("no images have been generated")
    elif bad:
        out.append(f"{len(bad)} image(s) are not generated yet: {', '.join(bad[:4])}{'…' if len(bad) > 4 else ''}")
    return out


def build_package(project: Project, dest: Path, allow_partial: bool = False) -> Path:
    """Write the package into dest (replaced), and a zip beside it. Refuses an incomplete pack unless allow_partial."""
    if project.status not in (ProjectStatus.REWRITTEN, ProjectStatus.GENERATED, ProjectStatus.EXPORTED):
        raise GateError(f"nothing to export yet: project is {project.status.value}")
    gaps = missing_for_export(project)
    if gaps and not allow_partial:
        raise GateError("the pack is incomplete: " + "; ".join(gaps))
    if dest.exists():
        shutil.rmtree(dest)
    for sub in ("character_bible", "costume_bible", "scene_keyframes"):
        (dest / sub).mkdir(parents=True)
    (dest / "scene_breakdown.json").write_text(json.dumps(scene_breakdown(project), indent=2, ensure_ascii=False))
    (dest / "adapted_screenplay.pdf").write_bytes(adapted_screenplay_pdf(project))
    (dest / "continuity_report.pdf").write_bytes(continuity_report_pdf(project))

    _write_bibles(project, dest)
    for a in project.assets:
        if a.kind == AssetKind.SCENE_KEYFRAME and asset_path(project, a).exists():
            shutil.copy(asset_path(project, a), dest / "scene_keyframes" / f"{a.entity_id}.png")
            _dump(dest / "scene_keyframes" / f"{a.entity_id}.json", {"scene_id": a.entity_id, "image": _provenance(a)})
    z = dest.with_suffix(".zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(dest.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(dest))
    return z
