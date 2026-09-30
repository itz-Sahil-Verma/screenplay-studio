import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.llm.fake import FakeLLM
from app.main import app
from app.models import Project
from tests.test_plan import SCENES, entity_json, ready_project, scene_json
from tests.test_rewrite import ACTION, DIALOGUE, approved_project, rewrite_json

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_TEXT = (FIXTURES / "sample_screenplay.txt").read_text()
SELECTION = {"pack_id": "majhi_punjabi", "region": "Amritsar", "setting": "rural", "output_script": "gurmukhi"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(deps, "SYNC_JOBS", True)
    deps.JOBS.clear()
    return TestClient(app, raise_server_exceptions=False)


def script_models(monkeypatch, extract=None, adapt=None):
    """Scripted models for the two steps. The extract model serves extraction AND the normalize proposal."""
    src = Project.model_validate_json((FIXTURES / "extracted_sample.json").read_text())
    real_extract = [s.extraction.model_dump_json() for s in src.source_scenes] + ["{}"]
    p = ready_project()
    real_adapt = [entity_json(p)] + [scene_json(s) for s in SCENES]
    models = {"extract": extract or FakeLLM(real_extract), "adapt": adapt or FakeLLM(real_adapt)}
    monkeypatch.setattr(deps, "llm_for", lambda step: models[step])
    return models


def create(api, **over):
    body = {**SELECTION, "text": SAMPLE_TEXT, **over}
    return api.post("/api/projects", data={k: v for k, v in body.items() if v is not None})


def run(api, pid, stage):
    r = api.post(f"/api/projects/{pid}/run/{stage}")
    assert r.status_code == 202, r.text
    return api.get(f"/api/projects/{pid}").json()


def to_plan_ready(api, monkeypatch):
    script_models(monkeypatch)
    pid = create(api).json()["id"]
    for stage in ("extract", "normalize", "plan"):
        run(api, pid, stage)
    return pid


# ---- creating a project -------------------------------------------------------------------------------------
def test_packs_endpoint_feeds_the_dropdowns(api):
    packs = api.get("/api/packs").json()
    assert packs[0]["id"] == "majhi_punjabi" and packs[0]["default_script"] == "gurmukhi"
    assert {"id": "gurmukhi", "label": "Gurmukhi"} in packs[0]["scripts"]


def test_create_from_pasted_text_splits_scenes_and_reports_problems(api):
    r = create(api)
    assert r.status_code == 201 and r.json()["scenes"] == 4
    assert any("preamble" in m for m in r.json()["problems"])  # the title line
    assert api.get(f"/api/projects/{r.json()['id']}").json()["status"] == "created"


def test_create_from_an_uploaded_file(api):
    r = api.post("/api/projects", data=SELECTION, files={"file": ("play.txt", SAMPLE_TEXT.encode(), "text/plain")})
    assert r.status_code == 201 and r.json()["scenes"] == 4


@pytest.mark.parametrize("over,expect", [
    ({"text": None}, "provide a screenplay"),
    ({"text": "   "}, "provide a screenplay"),
    ({"region": "Ludhiana"}, "region"),
    ({"output_script": "klingon"}, "script"),
    ({"pack_id": "nowhere"}, "unknown culture pack"),
    ({"setting": "moon"}, ""),
])
def test_create_validation(api, over, expect):
    r = create(api, **over)
    assert r.status_code == 422 and expect in json.dumps(r.json())


def test_unsupported_upload_is_rejected_with_a_reason(api):
    r = api.post("/api/projects", data=SELECTION, files={"file": ("play.rtf", b"hello", "text/plain")})
    assert r.status_code == 422 and "unsupported file type" in r.text


def test_unknown_project_is_a_clean_404(api):
    r = api.get("/api/projects/nope")
    assert r.status_code == 404 and r.json() == {"detail": "unknown project 'nope'"}


# ---- the whole flow over HTTP ---------------------------------------------------------------------------------
def test_full_flow_from_upload_to_approval(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    p = api.get(f"/api/projects/{pid}").json()
    assert p["status"] == "plan_ready" and p["continuity_checked"] and p["job"]["state"] == "done"
    assert len(p["characters"]) == 5 and len(p["source_scenes"]) == 4
    letter = next(w for w in p["warnings"] if w["code"] == "PROP_HOLDER_MISMATCH")
    assert letter["severity"] == "error" and letter["id"] in p["blocking_warning_ids"]

    # blockers are explicit and specific
    assert any("unexplained costume change" in b for b in api.get(f"/api/projects/{pid}/blockers/costumes").json()["blockers"])
    r = api.patch(f"/api/projects/{pid}/plan/costume/COST_RAVI_02", json={"change_reason": "changes for the evening"})
    assert r.status_code == 200 and r.json()["affected_scenes"] == ["SC03", "SC04"]
    for sid in ("SC03", "SC04"):
        assert api.post(f"/api/projects/{pid}/plan/scenes/{sid}/keep").status_code == 200
    for d in api.get(f"/api/projects/{pid}").json()["decisions"]:
        assert api.post(f"/api/projects/{pid}/decisions/{d['id']}/review", json={"status": "accepted"}).status_code == 200

    assert api.post(f"/api/projects/{pid}/approve/characters").json()["approved"] is False
    api.post(f"/api/projects/{pid}/approve/costumes")
    last = api.post(f"/api/projects/{pid}/approve/plan").json()
    assert last["approved"] is False and "PROP_HOLDER_MISMATCH" in last["blocked_by"]  # the contradiction is still open

    ack = api.post(f"/api/projects/{pid}/warnings/acknowledge",
                   json={"warning_id": letter["id"], "note": "Hari hands it back off-screen"})
    assert ack.json()["approved"] is True
    final = api.get(f"/api/projects/{pid}").json()
    assert final["status"] == "approved"
    assert next(c for c in final["characters"] if c["id"] == "CHAR_RAVI")["adapted_name"]  # plan applied to records

    r = api.post(f"/api/projects/{pid}/unapprove", json={"what": "costumes"})
    assert r.json()["status"] == "plan_ready" and r.json()["approval"]["characters"] is True


def test_project_survives_a_restart_because_everything_is_on_disk(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    deps.JOBS.clear()  # as if the server restarted
    p = api.get(f"/api/projects/{pid}").json()
    assert p["status"] == "plan_ready" and p["plan"]["entities"]["characters"]
    listing = api.get("/api/projects").json()
    assert [x["id"] for x in listing] == [pid]
    assert listing[0]["status"] == "plan_ready" and listing[0]["culture"] == "Majhi Punjabi" and listing[0]["scenes"] == 4
    assert listing[0]["flagged_decisions"] == sum(d["uncertain"] for d in api.get(f"/api/projects/{pid}").json()["decisions"])


# ---- guards ----------------------------------------------------------------------------------------------------
def test_stages_must_run_in_order(api, monkeypatch):
    script_models(monkeypatch)
    pid = create(api).json()["id"]
    for stage in ("normalize", "plan"):
        r = api.post(f"/api/projects/{pid}/run/{stage}")
        assert r.status_code == 409, stage
    assert api.post(f"/api/projects/{pid}/run/nonsense").status_code == 404
    run(api, pid, "extract")
    assert api.post(f"/api/projects/{pid}/run/extract").status_code == 409  # already extracted


def test_approving_too_early_is_409_with_the_reason(api, monkeypatch):
    script_models(monkeypatch)
    pid = create(api).json()["id"]
    r = api.post(f"/api/projects/{pid}/approve/characters")
    assert r.status_code == 409 and "plan_ready" in r.json()["detail"]


def test_invalid_review_requests_are_422_not_500(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    assert api.post(f"/api/projects/{pid}/merge", json={"kind": "character", "keep_id": "CHAR_RAVI", "drop_id": "CHAR_MEERA"}).status_code == 422
    assert api.post(f"/api/projects/{pid}/merge", json={"kind": "prop", "keep_id": "PROP_CUP", "drop_id": "PROP_CUP"}).status_code == 422
    assert api.patch(f"/api/projects/{pid}/characters/CHAR_ANU", json={"id": "X"}).status_code == 422
    assert api.post(f"/api/projects/{pid}/decisions/DEC999/review", json={"status": "accepted"}).status_code == 422
    assert api.post(f"/api/projects/{pid}/warnings/acknowledge", json={"warning_id": "x", "note": "n"}).status_code == 422
    letter = next(w for w in api.get(f"/api/projects/{pid}").json()["warnings"] if w["severity"] == "error")
    assert api.post(f"/api/projects/{pid}/warnings/acknowledge", json={"warning_id": letter["id"]}).status_code == 422  # note required


def test_edit_and_merge_return_only_the_affected_scenes(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    assert api.patch(f"/api/projects/{pid}/characters/CHAR_ANU", json={"role": "younger daughter"}).json() == {"affected_scenes": ["SC01", "SC03", "SC04"]}
    r = api.post(f"/api/projects/{pid}/merge", json={"kind": "character", "keep_id": "CHAR_UNCLE_HARI", "drop_id": "CHAR_POSTMAN"})
    assert r.json() == {"affected_scenes": ["SC01", "SC02"]}
    assert not any(c["id"] == "CHAR_POSTMAN" for c in api.get(f"/api/projects/{pid}").json()["characters"])


def test_mutations_are_refused_while_a_job_runs_but_reading_is_fine(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    deps.JOBS[pid] = {"name": "plan", "state": "running", "error": "", "started": 0, "finished": None}
    assert api.get(f"/api/projects/{pid}").status_code == 200
    r = api.patch(f"/api/projects/{pid}/characters/CHAR_ANU", json={"role": "x"})
    assert r.status_code == 409 and "job is running" in r.json()["detail"]
    assert api.post(f"/api/projects/{pid}/run/plan").status_code == 409
    deps.JOBS[pid]["state"] = "done"
    assert api.patch(f"/api/projects/{pid}/characters/CHAR_ANU", json={"role": "x"}).status_code == 200


def test_a_failed_job_is_reported_and_can_be_retried(api, monkeypatch):
    src = Project.model_validate_json((FIXTURES / "extracted_sample.json").read_text())
    good = [s.extraction.model_dump_json() for s in src.source_scenes]
    script_models(monkeypatch, extract=FakeLLM([good[0], RuntimeError("model down"), good[2], good[3]]))
    pid = create(api).json()["id"]
    p = run(api, pid, "extract")
    assert p["status"] == "created"  # scene 2 failed, so not extracted
    assert "model down" in p["source_scenes"][1]["error"] and any("scene 2" in m for m in p["review_problems"])
    monkeypatch.setattr(deps, "llm_for", lambda step: FakeLLM([good[1]]))
    p = run(api, pid, "extract")  # only the failed scene is redone
    assert p["status"] == "extracted" and p["source_scenes"][1]["error"] == ""


def test_a_job_that_raises_is_recorded_not_crashed(api, monkeypatch):
    script_models(monkeypatch)
    pid = create(api).json()["id"]
    run(api, pid, "extract")
    monkeypatch.setattr(deps, "llm_for", lambda step: (_ for _ in ()).throw(RuntimeError("no key configured")))
    run(api, pid, "normalize")
    job = api.get(f"/api/projects/{pid}/job").json()
    assert job["state"] == "failed" and "no key configured" in job["error"]


# ---- the rewrite over HTTP ---------------------------------------------------------------------------------------
def approve_everything(api, pid):
    api.patch(f"/api/projects/{pid}/plan/costume/COST_RAVI_02", json={"change_reason": "changes for the evening"})
    for sid in ("SC03", "SC04"):
        api.post(f"/api/projects/{pid}/plan/scenes/{sid}/keep")
    p = api.get(f"/api/projects/{pid}").json()
    for d in p["decisions"]:
        api.post(f"/api/projects/{pid}/decisions/{d['id']}/review", json={"status": "accepted"})
    letter = next(w for w in p["warnings"] if w["severity"] == "error")
    api.post(f"/api/projects/{pid}/warnings/acknowledge", json={"warning_id": letter["id"], "note": "intentional"})
    for what in ("characters", "costumes", "plan"):
        api.post(f"/api/projects/{pid}/approve/{what}")
    assert api.get(f"/api/projects/{pid}").json()["status"] == "approved"


def test_rewrite_needs_approval_then_runs_and_exposes_screenplay_and_comparison(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    assert api.post(f"/api/projects/{pid}/run/rewrite").status_code == 409  # not approved yet
    assert api.get(f"/api/projects/{pid}/screenplay").status_code == 404
    approve_everything(api, pid)

    ref = approved_project()
    monkeypatch.setattr(deps, "llm_for", lambda step: FakeLLM([rewrite_json(ref, s) for s in SCENES]))
    p = run(api, pid, "rewrite")
    assert p["status"] == "rewritten" and len(p["adapted_scenes"]) == 4 and p["rewrite_failed"] == {}

    text = api.get(f"/api/projects/{pid}/screenplay").text
    assert DIALOGUE in text and ACTION in text and "line 1" not in text
    assert "[line 1]" in api.get(f"/api/projects/{pid}/screenplay?gloss=true").text

    cmp = api.get(f"/api/projects/{pid}/comparison").json()
    assert [c["scene_id"] for c in cmp] == SCENES
    assert "POSTMAN" in cmp[0]["source_text"] and cmp[0]["adapted"]["lines"][0]["source_line"] == 1
    assert cmp[0]["failed"] == "" and all(isinstance(c["decisions"], list) for c in cmp)


def test_regenerating_one_scene_over_http(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    approve_everything(api, pid)
    ref = approved_project()
    monkeypatch.setattr(deps, "llm_for", lambda step: FakeLLM([rewrite_json(ref, s) for s in SCENES]))
    run(api, pid, "rewrite")
    fresh = FakeLLM([rewrite_json(ref, "SC02", lambda d: d["lines"][0].update(gloss="second take"))])
    monkeypatch.setattr(deps, "llm_for", lambda step: fresh)
    assert api.post(f"/api/projects/{pid}/rewrite/scene/SC02").status_code == 202
    p = api.get(f"/api/projects/{pid}").json()
    assert len(fresh.calls) == 1 and p["adapted_scenes"][1]["lines"][0]["gloss"] == "second take"
    assert len(p["adapted_scenes"]) == 4 and p["status"] == "rewritten"


# ---- one-click analysis, real progress, and saving as it goes -------------------------------------------------
def test_analyse_chains_extract_normalize_and_plan_in_one_job_with_progress(api, monkeypatch):
    script_models(monkeypatch)
    pid = create(api).json()["id"]
    r = api.post(f"/api/projects/{pid}/run/analyse")
    assert r.status_code == 202
    p = api.get(f"/api/projects/{pid}").json()
    assert p["status"] == "plan_ready" and p["continuity_checked"] and p["plan"]["entities"]
    job = api.get(f"/api/projects/{pid}/job").json()
    assert job["state"] == "done" and job["done"] == job["total"] and job["progress"] == "Planning scenes"


def test_finished_scenes_are_on_disk_while_the_job_is_still_running(api, monkeypatch):
    """Progressive persistence: when scene 2 is being planned, scene 1's plan has already been saved."""
    from app.storage import load_project
    script_models(monkeypatch)
    pid = create(api).json()["id"]
    run(api, pid, "extract")
    run(api, pid, "normalize")
    ref = ready_project()
    seen = {}

    class Spy:
        name = "spy"

        def complete_json(self, system, prompt, schema):
            if schema.__name__ == "EntityPlan":
                return entity_json(ref)
            sid = re.search(r"Set scene_id to '(SC\d+)'", prompt).group(1)
            if sid == "SC03":
                seen["planned_on_disk_when_sc03_starts"] = sorted(load_project(pid).plan.scenes)
            return scene_json(sid)

    monkeypatch.setattr(deps, "llm_for", lambda step: Spy())
    run(api, pid, "plan")
    assert seen["planned_on_disk_when_sc03_starts"] == ["SC01", "SC02"]


def test_analyse_stops_with_a_clear_reason_if_a_scene_cannot_be_extracted_and_resumes(api, monkeypatch):
    src = Project.model_validate_json((FIXTURES / "extracted_sample.json").read_text())
    good = [s.extraction.model_dump_json() for s in src.source_scenes]
    script_models(monkeypatch, extract=FakeLLM([good[0], RuntimeError("model down"), good[2], good[3]]))
    pid = create(api).json()["id"]
    api.post(f"/api/projects/{pid}/run/analyse")
    job = api.get(f"/api/projects/{pid}/job").json()
    assert job["state"] == "failed" and "scene(s) [2] could not be extracted" in job["error"]
    assert api.get(f"/api/projects/{pid}").json()["status"] == "created"
    retry_extract = FakeLLM([good[1], "{}"])
    p = ready_project()
    monkeypatch.setattr(deps, "llm_for", lambda step: retry_extract if step == "extract" else FakeLLM([entity_json(p)] + [scene_json(s) for s in SCENES]))
    api.post(f"/api/projects/{pid}/run/analyse")
    assert api.get(f"/api/projects/{pid}/job").json()["state"] == "done"
    assert api.get(f"/api/projects/{pid}").json()["status"] == "plan_ready"  # resumed: only scene 2 was re-extracted


def test_analyse_is_refused_once_the_plan_exists(api, monkeypatch):
    pid = to_plan_ready(api, monkeypatch)
    assert api.post(f"/api/projects/{pid}/run/analyse").status_code == 409
