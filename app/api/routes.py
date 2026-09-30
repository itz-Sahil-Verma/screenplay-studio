"""HTTP API. Thin: every rule lives in app.review / app.pipeline, so nothing here can bypass a gate."""
from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app import review
from app.culture_packs.loader import list_packs, load_pack, load_scripts
from app.ingestion import read_document, read_pasted
from app.models import AdaptationDecision, AdaptedScene, CultureSelection, GateError, Project, ProjectStatus, Setting
from app.models import ReviewStatus
from app.pipeline import (build_plan, check_continuity, normalize, prepare_source, replan_entities, replan_scene,
                          rewrite_scene, rewrite_screenplay, run_extraction, screenplay_text)
from app.export import build_package, missing_for_export
from app.images import generate_assets, regenerate_asset
from app.images.generate import asset_path
from app.storage import project_dir, save_project
from app.config import settings

from . import deps

router = APIRouter(prefix="/api")


class MergeBody(BaseModel):
    kind: str
    keep_id: str
    drop_id: str


class ReviewBody(BaseModel):
    status: str
    adapted: str | None = None
    note: str = ""


class AckBody(BaseModel):
    warning_id: str
    acknowledged: bool = True
    note: str = ""


class UnapproveBody(BaseModel):
    what: str | None = None


# ---- response models: they make the OpenAPI schema (and the UI's generated types) match reality ----
class JobInfo(BaseModel):
    name: str
    state: str  # running | done | failed
    error: str = ""
    started: float | None = None
    finished: float | None = None
    progress: str = ""  # what it is doing right now, e.g. "Planning scenes"
    done: int | None = None  # units finished (scenes), and out of how many
    total: int | None = None


class ProjectView(Project):
    """The whole project plus what the UI needs to render it."""

    job: JobInfo | None = None
    blocking_warning_ids: list[str] = []  # ids of unresolved ERROR warnings
    review_problems: list[str] = []  # everything a reviewer should look at


class ProjectSummary(BaseModel):
    id: str
    source_filename: str
    status: str
    created_at: str
    culture: str
    region: str
    scenes: int
    characters: int
    decisions: int
    flagged_decisions: int
    unreviewed_decisions: int = 0  # decisions nobody has accepted, edited or rejected yet
    job: JobInfo | None = None


class Created(BaseModel):
    id: str
    scenes: int
    problems: list[str]


class ApprovalResult(BaseModel):
    approved: bool
    status: str = ""
    waiting_for: list[str] = []
    blocked_by: str | None = None


class Blockers(BaseModel):
    what: str
    blockers: list[str]


class AffectedScenes(BaseModel):
    affected_scenes: list[str]


class ComparisonScene(BaseModel):
    scene_id: str
    source_text: str
    adapted: AdaptedScene | None = None
    decisions: list[AdaptationDecision]
    failed: str = ""


def _view(project: Project) -> ProjectView:
    return ProjectView.model_validate({
        **project.model_dump(), "job": deps.JOBS.get(project.id),
        "blocking_warning_ids": [w.id for w in project.blocking_warnings], "review_problems": project.all_problems})


# ---- setup ---------------------------------------------------------------------------------------------
@router.get("/packs")
def packs():
    scripts = load_scripts()
    return [{"id": p.id, "culture": p.culture, "regions": p.regions, "settings": [s.value for s in p.settings],
             "scripts": [{"id": s, "label": scripts[s].label} for s in p.supported_scripts],
             "default_script": p.default_script, "avoid_mixing_with": p.avoid_mixing_with,
             "facts": len(p.facts), "flagged_facts": sum(f.flagged for f in p.facts)} for p in list_packs()]


@router.post("/projects", status_code=201, response_model=Created)
async def create_project(pack_id: str = Form(...), region: str = Form(...), setting: str = Form(...),
                         output_script: str = Form(...), text: str | None = Form(None),
                         file: UploadFile | None = File(None)):
    if file is not None and file.filename:
        data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"file is larger than {settings.max_upload_mb} MB; a 3-5 scene screenplay is far smaller")
        ingest = read_document(data, file.filename)
        name = file.filename
    elif text and len(text) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"pasted text is larger than {settings.max_upload_mb} MB")
    elif text and text.strip():
        ingest, name = read_pasted(text), "pasted.txt"
    else:
        raise HTTPException(422, "provide a screenplay: paste text or upload a TXT, DOCX or PDF file")
    if not ingest.text:
        raise HTTPException(422, "; ".join(ingest.problems) or "no text could be extracted")
    try:
        selection = CultureSelection(pack_id=pack_id, region=region, setting=Setting(setting), output_script=output_script)
        selection.validate_against(load_pack(pack_id), load_scripts())
    except KeyError as e:
        raise HTTPException(422, f"unknown culture pack {pack_id!r}") from e
    project = Project(source_filename=name, selection=selection)
    project.extraction_problems = list(ingest.problems)
    scene_problems = prepare_source(project, ingest.text)
    project.extraction_problems = [*ingest.problems, *scene_problems]
    save_project(project)
    return {"id": project.id, "scenes": len(project.source_scenes), "problems": project.extraction_problems}


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects():
    root = settings.workspace
    out = []
    for d in (sorted(root.iterdir()) if root.exists() else []):
        if not (d / "project.json").exists():
            continue
        try:
            p = deps.read_project(d.name)
        except Exception:  # noqa: BLE001: one unreadable project must not hide the others
            continue
        sel = p.selection
        pack = next((k for k in list_packs() if sel and k.id == sel.pack_id), None)
        out.append(ProjectSummary(
            id=p.id, source_filename=p.source_filename, status=p.status.value, created_at=p.created_at.isoformat(),
            culture=pack.culture if pack else "", region=sel.region if sel else "", scenes=len(p.source_scenes),
            characters=len(p.characters), decisions=len(p.decisions), flagged_decisions=sum(d.uncertain for d in p.decisions),
            unreviewed_decisions=sum(d.status.value == "proposed" for d in p.decisions),
            job=deps.JOBS.get(p.id)))
    return sorted(out, key=lambda s: s.created_at, reverse=True)


@router.get("/projects/{pid}", response_model=ProjectView)
def get_project(pid: str):
    return _view(deps.read_project(pid))


@router.get("/projects/{pid}/job", response_model=JobInfo | dict)
def get_job(pid: str):
    deps.read_project(pid)
    return deps.JOBS.get(pid) or {"state": "idle"}


# ---- pipeline stages (background jobs) ---------------------------------------------------------------------
def _precheck(p: Project, stage: str) -> None:
    if stage == "extract" and p.status != ProjectStatus.CREATED:
        raise GateError(f"extraction runs on a new project, not {p.status.value}")
    if stage == "normalize" and p.status not in (ProjectStatus.EXTRACTED, ProjectStatus.NORMALIZED):
        raise GateError(f"normalize needs an extracted project, not {p.status.value}")
    if stage == "analyse" and p.status not in (ProjectStatus.CREATED, ProjectStatus.EXTRACTED, ProjectStatus.NORMALIZED):
        raise GateError(f"the analysis runs on a project that has not been planned yet, not {p.status.value}")
    if stage == "rewrite" and p.status not in (ProjectStatus.APPROVED, ProjectStatus.REWRITTEN):
        raise GateError(f"the rewrite needs an approved project, not {p.status.value}: approve characters, costumes and plan first")
    if stage == "visuals":
        p.assert_can_generate_images()
    if stage == "plan" and (p.status not in (ProjectStatus.NORMALIZED, ProjectStatus.PLAN_READY) or not p.continuity_checked):
        raise GateError("planning needs a normalized project with the continuity check done (run 'normalize' first)")


@router.post("/projects/{pid}/run/{stage}", status_code=202, response_model=JobInfo)
def run_stage(pid: str, stage: str, force: bool = False):
    if stage not in ("extract", "normalize", "plan", "rewrite", "analyse", "visuals"):
        raise HTTPException(404, "stage must be extract, normalize, plan, rewrite, analyse or visuals")
    deps.ensure_idle(pid)
    _precheck(deps.read_project(pid), stage)

    def job(p: Project, report):
        if stage == "extract":
            run_extraction(p, deps.llm_for("extract"), on_progress=report)
        elif stage == "normalize":
            normalize(p, deps.llm_for("extract"), force=force)
            check_continuity(p)
        elif stage == "rewrite":
            rewrite_screenplay(p, deps.llm_for("adapt"), on_progress=report)
        elif stage == "analyse":
            _analyse(p, report)
        elif stage == "visuals":
            generate_assets(p, deps.image_for(), load_pack(p.selection.pack_id), on_progress=report)
        else:
            build_plan(p, deps.llm_for("adapt"), on_progress=report)

    return deps.start_job(pid, stage, job)


def _analyse(p: Project, report) -> None:
    """Extract, normalize, check continuity and plan in ONE job, so nobody has to click between stages. Each stage
    only does what is still missing, so running it again after a failure resumes from where it stopped."""
    if p.status == ProjectStatus.CREATED:
        run_extraction(p, deps.llm_for("extract"), on_progress=report)
        if p.status == ProjectStatus.CREATED:
            failed = [s.number for s in p.source_scenes if s.extraction is None]
            raise RuntimeError(f"scene(s) {failed} could not be extracted. Run the analysis again to retry only those.")
    if p.status == ProjectStatus.EXTRACTED:
        report("Merging aliases and checking continuity", 0, 1)
        normalize(p, deps.llm_for("extract"))
        check_continuity(p)
        report("Merging aliases and checking continuity", 1, 1)
    if p.status == ProjectStatus.NORMALIZED:
        if not p.continuity_checked:
            check_continuity(p)
        build_plan(p, deps.llm_for("adapt"), on_progress=report)


@router.post("/projects/{pid}/replan/scene/{scene_id}", status_code=202, response_model=JobInfo)
def replan_one_scene(pid: str, scene_id: str):
    return deps.start_job(pid, f"replan {scene_id}", lambda p, report: replan_scene(p, scene_id, deps.llm_for("adapt")))


@router.post("/projects/{pid}/rewrite/scene/{scene_id}", status_code=202, response_model=JobInfo)
def rewrite_one_scene(pid: str, scene_id: str):
    """Regenerate one scene's rewrite, bypassing the cache (an explicit "try again")."""
    deps.ensure_idle(pid)
    _precheck(deps.read_project(pid), "rewrite")
    return deps.start_job(pid, f"rewrite {scene_id}", lambda p, report: rewrite_scene(p, scene_id, deps.llm_for("adapt"), fresh=True))


@router.get("/projects/{pid}/screenplay", response_class=PlainTextResponse)
def screenplay(pid: str, gloss: bool = False):
    p = deps.read_project(pid)
    if not p.adapted_scenes:
        raise HTTPException(404, "there is no adapted screenplay yet")
    return screenplay_text(p, with_gloss=gloss)


@router.get("/projects/{pid}/comparison", response_model=list[ComparisonScene])
def comparison(pid: str):
    """Source next to adapted, per scene, with the decisions that explain the changes."""
    p = deps.read_project(pid)
    adapted = {a.source_scene_id: a for a in p.adapted_scenes}
    out = []
    for s in sorted(p.scenes, key=lambda s: s.number):
        a = adapted.get(s.scene_id)
        out.append({
            "scene_id": s.scene_id, "source_text": s.source_text,
            "adapted": a.model_dump(mode="json") if a else None,
            "decisions": [d.model_dump(mode="json") for d in p.decisions
                          if d.status != ReviewStatus.REJECTED and s.scene_id in d.source_scene_ids],
            "failed": p.rewrite_failed.get(s.scene_id, ""),
        })
    return out


@router.post("/projects/{pid}/replan/entities", status_code=202, response_model=JobInfo)
def replan_all_entities(pid: str):
    return deps.start_job(pid, "replan entities", lambda p, report: replan_entities(p, deps.llm_for("adapt")))


@router.post("/projects/{pid}/recheck", response_model=ProjectView)
def recheck(pid: str):
    with deps.open_project(pid) as p:
        check_continuity(p)
        return _view(p)


# ---- review: edits, merges, decisions, warnings ---------------------------------------------------------------
@router.patch("/projects/{pid}/characters/{cid}", response_model=AffectedScenes)
def edit_character(pid: str, cid: str, fields: dict = Body(...)):
    with deps.open_project(pid) as p:
        return {"affected_scenes": review.edit_character(p, cid, **fields)}


@router.post("/projects/{pid}/merge", response_model=AffectedScenes)
def merge(pid: str, body: MergeBody):
    with deps.open_project(pid) as p:
        return {"affected_scenes": review.merge(p, body.kind, body.keep_id, body.drop_id)}


@router.patch("/projects/{pid}/plan/{kind}/{eid}", response_model=AffectedScenes)
def edit_plan(pid: str, kind: str, eid: str, fields: dict = Body(...)):
    with deps.open_project(pid) as p:
        return {"affected_scenes": review.edit_plan_entity(p, kind, eid, **fields)}


@router.post("/projects/{pid}/plan/scenes/{scene_id}/keep")
def keep_scene(pid: str, scene_id: str):
    with deps.open_project(pid) as p:
        review.keep_scene_plan(p, scene_id)
        return {"stale_scenes": p.plan.stale_scenes}


@router.post("/projects/{pid}/decisions/{did}/review", response_model=AdaptationDecision)
def review_decision(pid: str, did: str, body: ReviewBody):
    with deps.open_project(pid) as p:
        review.review_decision(p, did, body.status, body.adapted, body.note)
        return next(d.model_dump(mode="json") for d in p.decisions if d.id == did)


@router.post("/projects/{pid}/warnings/acknowledge", response_model=ApprovalResult)
def acknowledge(pid: str, body: AckBody):
    with deps.open_project(pid) as p:
        review.acknowledge_warning(p, body.warning_id, body.acknowledged, body.note)
        return review.try_finalize(p) if body.acknowledged and p.approval.complete else {"approved": False}


# ---- approval ------------------------------------------------------------------------------------------------------
@router.get("/projects/{pid}/blockers/{what}", response_model=Blockers)
def get_blockers(pid: str, what: str):
    return {"what": what, "blockers": review.blockers(deps.read_project(pid), what)}


@router.post("/projects/{pid}/approve/{what}", response_model=ApprovalResult)
def approve(pid: str, what: str):
    with deps.open_project(pid) as p:
        return review.approve(p, what)


@router.post("/projects/{pid}/unapprove")
def unapprove(pid: str, body: UnapproveBody = UnapproveBody()):
    with deps.open_project(pid) as p:
        review.unapprove(p, body.what)
        return {"status": p.status.value, "approval": p.approval.model_dump()}


# ---- images ----------------------------------------------------------------------------------------------------
@router.post("/projects/{pid}/assets/{aid}/regenerate", status_code=202, response_model=JobInfo)
def regenerate(pid: str, aid: str):
    """A new image for the same spec. Images made from the old one become stale; only they are redone next time."""
    deps.ensure_idle(pid)
    p = deps.read_project(pid)
    p.assert_can_generate_images()
    if p.asset(aid) is None:
        raise KeyError(f"unknown asset {aid!r}")
    return deps.start_job(pid, f"regenerate {aid}", lambda p, report: regenerate_asset(
        p, aid, deps.image_for(), load_pack(p.selection.pack_id), on_progress=report))


@router.get("/projects/{pid}/assets/{aid}/file")
def asset_file(pid: str, aid: str):
    p = deps.read_project(pid)
    a = p.asset(aid)
    path = asset_path(p, a) if a else None
    if not path or not path.exists():
        raise HTTPException(404, "this image has not been generated yet")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


# ---- export ----------------------------------------------------------------------------------------------------
@router.get("/projects/{pid}/export/status")
def export_status(pid: str):
    p = deps.read_project(pid)
    return {"missing": missing_for_export(p), "exported": p.status == ProjectStatus.EXPORTED,
            "zip_ready": (project_dir(pid) / "export.zip").exists()}


@router.post("/projects/{pid}/export")
def export(pid: str, allow_partial: bool = False):
    """Build the package. Refuses while images are missing, unless the reviewer explicitly accepts a partial pack."""
    with deps.open_project(pid) as p:
        build_package(p, project_dir(pid) / "export", allow_partial=allow_partial)
        if p.status == ProjectStatus.GENERATED:
            p.transition(ProjectStatus.EXPORTED)
    return {"zip": f"/api/projects/{pid}/export/download"}


@router.get("/projects/{pid}/export/download")
def export_download(pid: str):
    deps.read_project(pid)
    z = project_dir(pid) / "export.zip"
    if not z.exists():
        raise HTTPException(404, "export has not been built yet")
    return FileResponse(z, media_type="application/zip", filename=f"adaptation_{pid}.zip")
