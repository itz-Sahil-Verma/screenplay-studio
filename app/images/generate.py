"""Generation: reconcile assets with the approved records, then produce what is missing, in dependency order.

Principles (the same ones as the text pipeline):
  * approval gate first: nothing is generated before the project is approved (Project.assert_can_generate_images);
  * one image per unique appearance, conditioned on the approved reference images;
  * idempotent and resumable: only PENDING / FAILED / STALE assets are generated; finished ones are never repeated;
  * failures are isolated and explained: a failed reference fails only the images that depend on it;
  * every generated image is checked by code (decodes, right shape, not blank);
  * every asset stores the model, prompt and spec that reproduce it.
"""
import io
import logging
import time

from PIL import Image, ImageStat

from app.config import settings
from app.models import Asset, AssetKind, AssetStatus, CulturePack, Project, ProjectStatus
from app.pipeline.parallel import run_parallel
from app.storage import project_dir

from .base import ImageClient, ImageError
from .specs import desired_assets

log = logging.getLogger(__name__)
ORDER = (AssetKind.CHARACTER_REF, AssetKind.COSTUME_SHEET, AssetKind.SCENE_KEYFRAME)


def asset_path(project: Project, asset: Asset):
    return project_dir(project.id) / "images" / f"{asset.id}.png"


def verify_image(data: bytes, size: str) -> list[str]:
    """Deterministic checks. A model can return something that decodes but is useless (blank, wrong shape)."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001
        return [f"the image does not decode: {type(e).__name__}"]
    problems = []
    w, h = img.size
    ew, eh = (int(x) for x in size.split("x"))
    if min(w, h) < 64:
        problems.append(f"the image is tiny ({w}x{h})")
    if abs(w / h - ew / eh) > 0.06:
        problems.append(f"the image has the wrong shape ({w}x{h}, expected about {ew}x{eh})")
    if max(ImageStat.Stat(img.convert("RGB")).stddev) < 3:
        problems.append("the image is blank or a flat colour")
    return problems


def sync_assets(project: Project, pack: CulturePack) -> None:
    """Make project.assets match what the approved records call for. Unchanged assets are kept as they are; an asset
    whose inputs changed becomes STALE (its old image stays visible until replaced); assets for things that no longer
    exist are dropped; an asset marked generated whose file is gone becomes PENDING."""
    existing = {a.id: a for a in project.assets}
    merged: list[Asset] = []
    for want in desired_assets(project, pack):
        old = existing.get(want.id)
        if old is None:
            merged.append(want)
        elif old.spec_hash == want.spec_hash:
            if old.status in (AssetStatus.GENERATED, AssetStatus.STALE) and not asset_path(project, old).exists():
                old.status, old.path = AssetStatus.PENDING, ""
            merged.append(old)
        else:
            want.path, want.attempts = old.path, old.attempts
            want.status = AssetStatus.STALE if old.path and asset_path(project, old).exists() else AssetStatus.PENDING
            merged.append(want)
    project.assets = merged


def _read(project: Project, aid: str) -> bytes:
    a = project.asset(aid)
    if a is None or a.status not in (AssetStatus.GENERATED,) or not asset_path(project, a).exists():
        raise ImageError(f"its reference image {aid} is not available: generate or fix that one first")
    return asset_path(project, a).read_bytes()


def _make(project: Project, a: Asset, client: ImageClient) -> tuple[bytes, float]:
    """The model call for one asset. Read-only on the project, so safe in a worker thread."""
    t0 = time.perf_counter()
    if a.kind == AssetKind.CHARACTER_REF:
        data = client.generate(a.prompt, a.size)
    else:
        data = client.edit(a.prompt, [_read(project, r) for r in a.reference_asset_ids], a.size)
    return data, time.perf_counter() - t0


def _finish(project: Project) -> None:
    all_done = bool(project.assets) and all(a.status == AssetStatus.GENERATED for a in project.assets)
    if all_done and project.status == ProjectStatus.REWRITTEN:
        project.transition(ProjectStatus.GENERATED)
    elif not all_done and project.status == ProjectStatus.GENERATED:
        project.status = ProjectStatus.REWRITTEN  # something became stale or failed: the pack is no longer complete


def generate_assets(project: Project, client: ImageClient, pack: CulturePack, only: set[str] | None = None, on_progress=None) -> Project:
    project.assert_can_generate_images()
    sync_assets(project, pack)
    todo = [a for a in project.assets if a.status in (AssetStatus.PENDING, AssetStatus.FAILED, AssetStatus.STALE) and (only is None or a.id in only)]
    total, done = len(todo), 0
    if todo and project.status == ProjectStatus.EXPORTED:
        project.status = ProjectStatus.GENERATED  # the built package no longer matches the images: export again

    def apply(a: Asset, result, err):
        nonlocal done
        a.attempts += 1
        if err is not None:
            a.status, a.error = AssetStatus.FAILED, f"{type(err).__name__}: {str(err)[:300]}"
            log.error("%s failed: %s", a.id, a.error)
        else:
            data, seconds = result
            path = asset_path(project, a)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            a.path, a.model, a.seconds, a.error = f"images/{a.id}.png", client.model, round(seconds, 1), ""
            a.problems = verify_image(data, a.size)
            a.status = AssetStatus.GENERATED
        done += 1
        if on_progress:
            on_progress("Generating images", done, total)

    for kind in ORDER:  # a phase only starts when the previous one has finished: later images need the earlier ones
        phase = [a for a in todo if a.kind == kind]
        run_parallel(phase, lambda a: _make(project, a, client), apply, settings.image_concurrency)
    _finish(project)
    return project


def regenerate_asset(project: Project, asset_id: str, client: ImageClient, pack: CulturePack, on_progress=None) -> Project:
    """Generate one asset again (a new image for the same spec). Everything conditioned on the old image is now
    inconsistent with it, so those assets become STALE, and only they are redone next time."""
    project.assert_can_generate_images()
    sync_assets(project, pack)
    a = project.asset(asset_id)
    if a is None:
        raise ImageError(f"unknown asset {asset_id!r}")
    a.status = AssetStatus.PENDING
    generate_assets(project, client, pack, only={asset_id}, on_progress=on_progress)
    if a.status == AssetStatus.GENERATED:
        for dep in project.assets:
            if asset_id in dep.reference_asset_ids and dep.status == AssetStatus.GENERATED:
                dep.status = AssetStatus.STALE
    _finish(project)
    return project
