import base64
import io
import json
import threading

import httpx
import pytest
from PIL import Image

from app.config import settings
from app.culture_packs.loader import load_pack
from app.images import ImageError, desired_assets, generate_assets, regenerate_asset, sync_assets, verify_image
from app.images.fake import FakeImageClient
from app.images.flux import AzureFluxClient, flux_endpoint
from app.images.generate import asset_path
from app.images.specs import MAX_REFERENCES, spec_prompt
from app.models import AssetKind, AssetStatus, GateError, ProjectStatus
from app.pipeline import rewrite_screenplay
from tests.test_rewrite import approved_project, happy
from tests.test_review import get_ready_to_approve

PACK = load_pack("majhi_punjabi")
PNG = FakeImageClient().generate("seed", "1024x1536")


def rewritten_project():
    p = approved_project()
    rewrite_screenplay(p, happy(p))
    assert p.status == ProjectStatus.REWRITTEN
    return p


def by_kind(p, kind):
    return [a for a in p.assets if a.kind == kind]


# ---- FLUX client: the documented Foundry request format ---------------------------------------------------------
def flux(handler, model="FLUX.2-pro"):
    return AzureFluxClient(model=model, endpoint="https://myres.api.cognitive.microsoft.com", api_key="KEY",
                           http=httpx.Client(transport=httpx.MockTransport(handler)))


def ok_response(png=PNG):
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode()}]})


def test_flux_text_to_image_request_matches_the_documented_format():
    seen = {}

    def handler(req):
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=json.loads(req.content))
        return ok_response()

    assert flux(handler).generate("a fox", "1024x1536") == PNG
    assert seen["url"] == "https://myres.api.cognitive.microsoft.com/providers/blackforestlabs/v1/flux-2-pro?api-version=preview"
    assert seen["auth"] == "Bearer KEY"
    assert seen["body"] == {"model": "FLUX.2-pro", "prompt": "a fox", "width": 1024, "height": 1536, "output_format": "png"}


def test_flux_reference_images_go_as_input_image_input_image_2_and_so_on():
    seen = {}
    flux(lambda req: (seen.update(body=json.loads(req.content)), ok_response())[1]).edit("same person", [b"one", b"two", b"three"], "1536x1024")
    b = seen["body"]
    assert base64.b64decode(b["input_image"]) == b"one" and base64.b64decode(b["input_image_2"]) == b"two" and base64.b64decode(b["input_image_3"]) == b"three"
    assert (b["width"], b["height"]) == (1536, 1024)


def test_flux_pro_takes_8_references_and_flex_takes_10():
    assert flux(lambda r: ok_response()).max_references == 8 and flux(lambda r: ok_response(), "FLUX.2-flex").max_references == 10
    with pytest.raises(ImageError, match="at most 8"):
        flux(lambda r: ok_response()).edit("x", [b"a"] * 9, "1024x1024")


def test_flux_can_return_a_url_instead_of_base64():
    def handler(req):
        return httpx.Response(200, content=PNG) if req.url.host == "cdn.example" else httpx.Response(200, json={"data": [{"url": "https://cdn.example/i.png"}]})

    assert flux(handler).generate("x", "1024x1024") == PNG


@pytest.mark.parametrize("status,expect", [(404, "not found"), (401, "credentials"), (403, "credentials"), (400, "rejected the request")])
def test_flux_errors_say_what_to_fix(status, expect):
    with pytest.raises(ImageError, match=expect):
        flux(lambda r: httpx.Response(status, text="nope")).generate("x", "1024x1024")


def test_flux_retries_a_rate_limit_once_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.llm.base.time.sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) == 1 else ok_response()

    assert flux(handler).generate("x", "1024x1024") == PNG and len(calls) == 2


def test_flux_endpoint_is_derived_from_the_resource_name_or_overridden(monkeypatch):
    monkeypatch.setattr(settings, "azure_flux_endpoint", "")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://myres.openai.azure.com/")
    assert flux_endpoint() == "https://myres.api.cognitive.microsoft.com"
    monkeypatch.setattr(settings, "azure_flux_endpoint", "https://other.example.com/")
    assert flux_endpoint() == "https://other.example.com"


def test_unknown_flux_model_is_rejected():
    with pytest.raises(ImageError, match="AZURE_FLUX_MODEL"):
        AzureFluxClient(model="FLUX.9", endpoint="https://x", api_key="k")


# ---- OpenAI-style image client and the provider switch ------------------------------------------------------------
def test_azure_gpt_image_client_sends_references_in_order_and_decodes_the_result(monkeypatch):
    from app.images.azure import AzureImageClient
    monkeypatch.setattr(settings, "image_quality", "low")
    monkeypatch.setattr(settings, "image_input_fidelity", "high")
    sent = {}

    class Images:
        def edit(self, **kw):
            sent.update(kw)
            return type("R", (), {"data": [type("D", (), {"b64_json": base64.b64encode(PNG).decode()})()]})()

    c = AzureImageClient.__new__(AzureImageClient)
    c.model, c._client = "img", type("C", (), {"images": Images()})()
    assert c.edit("p", [b"A", b"B"], "1024x1536") == PNG
    assert [f[0] for f in sent["image"]] == ["reference_1.png", "reference_2.png"] and sent["image"][1][1] == b"B"
    assert sent["quality"] == "low" and sent["size"] == "1024x1536" and sent["input_fidelity"] == "high"


def test_provider_switch_names_what_is_missing_and_never_falls_back(monkeypatch):
    from app.images import get_image_client
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://r.openai.azure.com")
    monkeypatch.setattr(settings, "azure_openai_api_key", "k")
    monkeypatch.setattr(settings, "azure_deployment_image", "")
    monkeypatch.setattr(settings, "image_provider", "azure")
    with pytest.raises(ImageError, match="AZURE_DEPLOYMENT_IMAGE"):
        get_image_client()
    monkeypatch.setattr(settings, "image_provider", "azure_flux")
    assert get_image_client().name == "azure_flux"
    monkeypatch.setattr(settings, "image_provider", "midjourney")
    with pytest.raises(ImageError, match="unknown IMAGE_PROVIDER"):
        get_image_client()


# ---- specs: derived from the approved records ----------------------------------------------------------------------
def test_one_image_per_unique_appearance_and_the_first_costume_is_the_character_reference():
    p = approved_project()
    assets = desired_assets(p, PACK)
    assert len(by_kind(type("P", (), {"assets": assets})(), AssetKind.CHARACTER_REF)) == 5
    sheets = [a for a in assets if a.kind == AssetKind.COSTUME_SHEET]
    assert [a.entity_id for a in sheets] == ["COST_RAVI_02"]  # Ravi's SECOND costume only; every first costume is its character reference
    assert len(assets) == 5 + 1 + 4 and len({a.spec_hash for a in assets}) == len(assets)  # nothing is generated twice


def test_the_prompt_is_derived_from_the_spec_alone_so_the_stored_spec_reproduces_the_image():
    for a in desired_assets(approved_project(), PACK):
        assert a.prompt == spec_prompt(a.spec) and a.spec["size"] == a.size


def test_prompts_carry_the_approved_look_and_the_culture_not_source_placeholders():
    p = approved_project()
    ref = next(a for a in desired_assets(p, PACK) if a.id == "ASSET_CHARREF_CHAR_RAVI")
    ravi = next(c for c in p.characters if c.id == "CHAR_RAVI")
    assert ravi.physical_description in ref.prompt and ravi.adapted_name in ref.prompt and "Majhi Punjabi culture" in ref.prompt


def test_specs_are_deterministic():
    p = approved_project()
    a, b = desired_assets(p, PACK), desired_assets(p, PACK)
    assert [x.model_dump() for x in a] == [x.model_dump() for x in b]


def test_a_keyframe_lists_its_references_in_order_and_says_which_image_is_who():
    p = approved_project()
    kf = next(a for a in desired_assets(p, PACK) if a.id == "ASSET_KEYFRAME_SC01")
    assert kf.reference_asset_ids == [r["asset"] for r in kf.spec["refs"]]
    assert [x["image"] for x in kf.spec["pictured"]] == [1, 2, 3, 4]
    assert "reference image 1 is" in kf.prompt and "IDENTICAL" in kf.prompt


def test_keyframe_uses_the_costume_the_character_wears_in_that_scene():
    p = approved_project()
    kfs = {a.id: a for a in desired_assets(p, PACK)}
    assert "ASSET_COSTUME_COST_RAVI_02" in kfs["ASSET_KEYFRAME_SC03"].reference_asset_ids
    assert "ASSET_COSTUME_COST_RAVI_02" not in kfs["ASSET_KEYFRAME_SC01"].reference_asset_ids  # scene 1 still has his first look


def test_scenes_with_more_characters_than_the_reference_limit_describe_the_rest_in_words(monkeypatch):
    monkeypatch.setattr("app.images.specs.MAX_REFERENCES", 2)
    kf = next(a for a in desired_assets(approved_project(), PACK) if a.id == "ASSET_KEYFRAME_SC01")
    assert len(kf.reference_asset_ids) == 2 and len(kf.spec["others"]) == 2 and "not pictured in a reference" in kf.prompt
    assert MAX_REFERENCES == 4


# ---- generation ----------------------------------------------------------------------------------------------------
def test_nothing_is_generated_before_approval():
    with pytest.raises(GateError):
        generate_assets(get_ready_to_approve(), FakeImageClient(), PACK)


def test_generation_runs_in_dependency_order_and_conditions_later_images_on_earlier_ones():
    p, c = rewritten_project(), FakeImageClient()
    generate_assets(p, c, PACK)
    kinds = [x["kind"] for x in c.calls]
    assert kinds == ["generate"] * 5 + ["edit"] * 5  # 5 text-to-image references, then 1 sheet + 4 keyframes, all conditioned on references
    assert all(a.status == AssetStatus.GENERATED and a.problems == [] for a in p.assets)
    ref_bytes = {a.id: asset_path(p, a).read_bytes() for a in p.assets}
    sheet = by_kind(p, AssetKind.COSTUME_SHEET)[0]
    call = next(x for x in c.calls if x["kind"] == "edit" and "wearing this costume" in x["prompt"])
    import hashlib
    assert call["refs"] == [hashlib.sha256(ref_bytes[sheet.reference_asset_ids[0]]).hexdigest()[:8]]  # the sheet was conditioned on Ravi's actual reference image


def test_every_asset_records_the_model_prompt_and_spec_that_reproduce_it():
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    for a in p.assets:
        assert a.model == "fake-image" and a.prompt == spec_prompt(a.spec) and a.spec_hash and a.path == f"images/{a.id}.png" and a.attempts == 1


def test_a_finished_pack_moves_the_project_to_generated_and_a_second_run_does_nothing():
    p, c = rewritten_project(), FakeImageClient()
    generate_assets(p, c, PACK)
    assert p.status == ProjectStatus.GENERATED
    again = FakeImageClient()
    generate_assets(p, again, PACK)
    assert again.calls == []  # idempotent: finished images are never made twice


def test_images_can_be_made_right_after_approval_without_changing_the_status():
    p = approved_project()
    generate_assets(p, FakeImageClient(), PACK)
    assert p.status == ProjectStatus.APPROVED and all(a.status == AssetStatus.GENERATED for a in p.assets)


def test_a_failed_reference_fails_only_what_depends_on_it_with_a_reason_and_retry_redoes_only_those():
    p = rewritten_project()
    ravi = next(c for c in p.characters if c.id == "CHAR_RAVI")
    bad = FakeImageClient(fail_for={ravi.adapted_name + ","})
    generate_assets(p, bad, PACK)
    st = {a.id: a.status for a in p.assets}
    assert st["ASSET_CHARREF_CHAR_RAVI"] == AssetStatus.FAILED
    assert st["ASSET_COSTUME_COST_RAVI_02"] == AssetStatus.FAILED and "reference image" in p.asset("ASSET_COSTUME_COST_RAVI_02").error
    assert all(st[f"ASSET_CHARREF_{c}"] == AssetStatus.GENERATED for c in ("CHAR_MEERA", "CHAR_ANU", "CHAR_POSTMAN", "CHAR_UNCLE_HARI"))
    assert p.status == ProjectStatus.REWRITTEN  # the pack is not complete
    failed = [a.id for a in p.assets if a.status == AssetStatus.FAILED]
    good = FakeImageClient()
    generate_assets(p, good, PACK)
    assert len(good.calls) == len(failed) and all(a.status == AssetStatus.GENERATED for a in p.assets) and p.status == ProjectStatus.GENERATED


def test_changing_a_character_marks_exactly_their_images_stale_and_nothing_else():
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    next(c for c in p.characters if c.id == "CHAR_ANU").physical_description = "tall, with a long plait and a scar on the chin"
    sync_assets(p, PACK)
    stale = {a.id for a in p.assets if a.status == AssetStatus.STALE}
    assert stale == {"ASSET_CHARREF_CHAR_ANU", "ASSET_KEYFRAME_SC01", "ASSET_KEYFRAME_SC03", "ASSET_KEYFRAME_SC04"}  # Anu and the scenes she is in
    assert p.asset("ASSET_KEYFRAME_SC02").status == AssetStatus.GENERATED  # scene 2 does not contain her
    redo = FakeImageClient()
    generate_assets(p, redo, PACK)
    assert len(redo.calls) == 4  # only the stale ones are regenerated


def test_regenerating_one_reference_makes_everything_conditioned_on_it_stale():
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    regen = FakeImageClient()
    regenerate_asset(p, "ASSET_CHARREF_CHAR_RAVI", regen, PACK)
    assert len(regen.calls) == 1 and regen.calls[0]["kind"] == "generate"
    stale = {a.id for a in p.assets if a.status == AssetStatus.STALE}
    assert "ASSET_COSTUME_COST_RAVI_02" in stale and {"ASSET_KEYFRAME_SC01", "ASSET_KEYFRAME_SC02"} <= stale  # they were made from the old face
    assert p.asset("ASSET_CHARREF_CHAR_MEERA").status == AssetStatus.GENERATED and p.status == ProjectStatus.REWRITTEN


def test_a_missing_file_is_noticed_and_regenerated():
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    asset_path(p, p.asset("ASSET_KEYFRAME_SC02")).unlink()
    c = FakeImageClient()
    generate_assets(p, c, PACK)
    assert len(c.calls) == 1


def test_assets_for_things_that_no_longer_exist_are_dropped():
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    from app.review import merge
    merge(p, "prop", "PROP_CUP", "PROP_TEA")  # unrelated: the asset set must not change
    assert len(p.assets) == 10
    p.characters = [c for c in p.characters if c.id != "CHAR_POSTMAN"]
    p.scenes[0].characters = [c for c in p.scenes[0].characters if c != "CHAR_POSTMAN"]
    p.costumes = [k for k in p.costumes if k.character_id != "CHAR_POSTMAN"]
    sync_assets(p, PACK)
    assert p.asset("ASSET_CHARREF_CHAR_POSTMAN") is None


def test_reference_images_are_generated_concurrently_within_a_phase(monkeypatch):
    monkeypatch.setattr(settings, "image_concurrency", 5)
    barrier = threading.Barrier(5, timeout=10)

    class Blocking(FakeImageClient):
        def generate(self, prompt, size):
            barrier.wait()  # all 5 character references must be in flight together
            return super().generate(prompt, size)

    p = rewritten_project()
    generate_assets(p, Blocking(), PACK)
    assert all(a.status == AssetStatus.GENERATED for a in p.assets)


def test_image_checks_catch_blank_wrong_shaped_and_corrupt_images():
    def png(size, color=None):
        buf = io.BytesIO()
        Image.new("RGB", size, color or (10, 200, 30)).save(buf, "PNG")
        return buf.getvalue()

    assert verify_image(PNG, "1024x1536") == []
    assert any("blank" in m for m in verify_image(png((128, 192)), "1024x1536"))
    assert any("wrong shape" in m for m in verify_image(FakeImageClient().generate("x", "1536x1024"), "1024x1536"))
    assert any("does not decode" in m for m in verify_image(b"not an image", "1024x1536"))
    assert any("tiny" in m for m in verify_image(png((32, 48)), "1024x1536"))


# ---- export package ------------------------------------------------------------------------------------------------
def test_export_refuses_an_incomplete_pack_and_says_why(tmp_path):
    from app.export import build_package
    p = rewritten_project()
    with pytest.raises(GateError, match="no images"):
        build_package(p, tmp_path / "out")
    ravi = next(c for c in p.characters if c.id == "CHAR_RAVI")
    generate_assets(p, FakeImageClient(fail_for={ravi.adapted_name + ","}), PACK)
    with pytest.raises(GateError, match="not generated"):
        build_package(p, tmp_path / "out")


def test_export_writes_the_layout_the_brief_asks_for(tmp_path):
    import zipfile
    from app.export import build_package
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    z = build_package(p, tmp_path / "out")
    out = tmp_path / "out"
    assert len(list((out / "character_bible").glob("*.png"))) == 5
    assert len(list((out / "costume_bible").glob("*.json"))) == len(p.costumes) == 6  # every variant has an entry
    costumes = {json.loads(f.read_text())["costume_id"]: json.loads(f.read_text()) for f in (out / "costume_bible").glob("*.json")}
    assert costumes["COST_RAVI_02"]["image"]["asset"] == "ASSET_COSTUME_COST_RAVI_02"
    assert costumes["COST_RAVI_01"]["image"]["asset"] == "ASSET_CHARREF_CHAR_RAVI" and "first look" in costumes["COST_RAVI_01"]["image_note"]
    assert all(k["garments"] and k["scenes"] for k in costumes.values())
    ravi = next(json.loads(f.read_text()) for f in (out / "character_bible").glob("*.json") if "CHAR_RAVI" in f.read_text())
    assert ravi["character_id"] == "CHAR_RAVI" and ravi["physical_description"] and "role" in ravi and ravi["costumes"] == ["COST_RAVI_01", "COST_RAVI_02"]
    assert len(list((out / "scene_keyframes").glob("*.png"))) == 4
    assert (out / "adapted_screenplay.pdf").read_bytes()[:4] == b"%PDF" and (out / "continuity_report.pdf").read_bytes()[:4] == b"%PDF"
    data = json.loads((out / "scene_breakdown.json").read_text())
    assert len(data["scenes"]) == 4 and data["characters"] and data["continuity_warnings"] is not None
    meta = json.loads(next((out / "scene_keyframes").glob("*.json")).read_text())
    assert meta["image"]["prompt"] and meta["image"]["spec"] and meta["image"]["model"]  # every image ships with what reproduces it
    assert "scene_breakdown.json" in zipfile.ZipFile(z).namelist()


def test_the_adapted_pdf_keeps_gurmukhi_text(tmp_path):
    import io
    from pypdf import PdfReader
    from app.export import adapted_screenplay_pdf
    text = "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(adapted_screenplay_pdf(rewritten_project()))).pages)
    assert "Adapted screenplay" in text and any("਀" <= ch <= "੿" for ch in text)


def test_export_marks_the_project_exported_through_the_api(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import deps
    from app.main import app
    from app.storage import save_project
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    save_project(p)
    c = TestClient(app)
    assert c.get(f"/api/projects/{p.id}/export/status").json()["missing"] == []
    assert c.get(f"/api/projects/{p.id}/export/download").status_code == 404
    assert c.post(f"/api/projects/{p.id}/export").status_code == 200
    assert c.get(f"/api/projects/{p.id}/export/download").headers["content-type"] == "application/zip"
    assert c.get(f"/api/projects/{p.id}").json()["status"] == "exported"


def test_visuals_job_and_regenerate_and_file_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import deps
    from app.main import app
    from app.storage import save_project
    monkeypatch.setattr(deps, "SYNC_JOBS", True)
    fake = FakeImageClient()
    monkeypatch.setattr(deps, "image_for", lambda: fake)
    p = rewritten_project()
    save_project(p)
    c = TestClient(app)
    assert c.get(f"/api/projects/{p.id}/assets/ASSET_KEYFRAME_SC01/file").status_code == 404
    assert c.post(f"/api/projects/{p.id}/run/visuals").status_code == 202
    r = c.get(f"/api/projects/{p.id}/assets/ASSET_KEYFRAME_SC01/file")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert c.get(f"/api/projects/{p.id}").json()["status"] == "generated"
    assert c.post(f"/api/projects/{p.id}/assets/ASSET_CHARREF_CHAR_RAVI/regenerate").status_code == 202
    assert c.post(f"/api/projects/{p.id}/assets/NOPE/regenerate").status_code == 404


def test_visuals_are_refused_before_approval(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.storage import save_project
    p = get_ready_to_approve()
    save_project(p)
    assert TestClient(app).post(f"/api/projects/{p.id}/run/visuals").status_code == 409


def test_a_foundry_project_endpoint_is_mapped_to_the_resource_for_images():
    from app.images.azure import image_base_url
    assert image_base_url("https://res.services.ai.azure.com/api/projects/my-proj") == "https://res.services.ai.azure.com/openai/v1/"
    assert image_base_url("https://res.openai.azure.com/") == "https://res.openai.azure.com/openai/v1/"
    assert image_base_url("https://res.openai.azure.com/openai/v1") == "https://res.openai.azure.com/openai/v1/"


def test_an_exported_project_can_still_redo_an_image_and_is_then_no_longer_exported(tmp_path):
    from app.export import build_package
    p = rewritten_project()
    generate_assets(p, FakeImageClient(), PACK)
    build_package(p, tmp_path / "out")
    p.transition(ProjectStatus.EXPORTED)
    regenerate_asset(p, "ASSET_KEYFRAME_SC02", FakeImageClient(), PACK)
    assert p.status == ProjectStatus.GENERATED  # the built package is out of date, so it must be exported again
    nothing = FakeImageClient()
    p.transition(ProjectStatus.EXPORTED)
    generate_assets(p, nothing, PACK)
    assert nothing.calls == [] and p.status == ProjectStatus.EXPORTED  # nothing to do: nothing changes


def test_two_quick_requests_start_only_one_job(monkeypatch):
    from app.api import deps
    from app.storage import save_project
    p = rewritten_project()
    save_project(p)
    started, release = threading.Event(), threading.Event()

    def slow(project, report):
        started.set()
        release.wait(5)

    results = []

    def go():
        try:
            deps.start_job(p.id, "slow", slow)
            results.append("ok")
        except deps.Busy:
            results.append("busy")

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    release.set()
    assert sorted(results) == ["busy"] * 7 + ["ok"]


def test_an_oversized_upload_is_refused_before_it_is_read(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    r = TestClient(app).post("/api/projects", data={"pack_id": "majhi_punjabi", "region": "Amritsar", "setting": "rural",
                                                     "output_script": "gurmukhi"},
                             files={"file": ("big.txt", b"x" * (1024 * 1024 + 10), "text/plain")})
    assert r.status_code == 413


def test_the_cache_never_mixes_models_or_culture_packs():
    from app.pipeline.extract import client_id
    from app.storage import make_key
    a = type("C", (), {"name": "azure", "deployment": "gpt-5"})()
    b = type("C", (), {"name": "gemini", "model": "gemini-2.5-pro"})()
    assert make_key("sys", "prompt", client_id(a)) != make_key("sys", "prompt", client_id(b))
    assert "CULTURE: " + PACK.culture in PACK.for_prompt()  # the pack is inside the prompt, so a different pack is a different key
