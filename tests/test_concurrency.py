"""Concurrency, budgets and telemetry. Every claim about parallel speed-up is proven with a barrier: a fake model
that makes N calls wait until all N are in flight at once, which a sequential implementation can never satisfy."""
import re
import threading

import pytest

from app.config import settings
from app.llm.metrics import Metrics
from app.models import ProjectStatus
from app.pipeline import build_plan, extract_scene, prepare_source, rewrite_screenplay, run_extraction
from app.pipeline.parallel import run_parallel
from app.pipeline.plan import MAX_ENTITY_DECISIONS, MAX_LIST_ITEMS, MAX_SCENE_DECISIONS
from tests.test_plan import SCENES, dec, entity_json, ready_project, scene_json
from tests.test_rewrite import approved_project, rewrite_json


class SceneAwareLLM:
    """A thread-safe fake that answers by WHAT was asked (schema + scene id), not by call order."""
    name = "fake"

    def __init__(self, respond, barrier_schema=None, parties=0):
        self.respond, self.barrier_schema = respond, barrier_schema
        self.barrier = threading.Barrier(parties, timeout=10) if parties else None
        self.lock, self.calls, self.threads = threading.Lock(), [], set()

    def complete_json(self, system, prompt, schema):
        with self.lock:
            self.calls.append(schema.__name__)
            self.threads.add(threading.get_ident())
        if self.barrier and schema.__name__ == self.barrier_schema:
            self.barrier.wait()  # raises BrokenBarrierError if the calls are not truly concurrent
        return self.respond(prompt, schema)


def scene_of(prompt):
    return re.search(r"Set scene_id to '(SC\d+)'", prompt).group(1)


# ---- run_parallel -------------------------------------------------------------------------------------
def test_sequential_mode_runs_inline_in_order_on_the_calling_thread():
    order, threads = [], set()
    run_parallel(range(5), lambda i: (threads.add(threading.get_ident()), i)[1], lambda i, r, e: order.append(r), workers=1)
    assert order == [0, 1, 2, 3, 4] and threads == {threading.get_ident()}


def test_workers_run_concurrently_but_results_are_applied_on_one_thread():
    barrier = threading.Barrier(4, timeout=10)
    applied_on, worked_on = set(), set()

    def work(i):
        worked_on.add(threading.get_ident())
        barrier.wait()  # all 4 must be in flight together
        return i * 2

    results = {}
    run_parallel(range(4), work, lambda i, r, e: (applied_on.add(threading.get_ident()), results.__setitem__(i, r)), workers=4)
    assert results == {0: 0, 1: 2, 2: 4, 3: 6}
    assert len(worked_on) == 4 and threading.get_ident() not in worked_on  # real worker threads
    assert applied_on == {threading.get_ident()}  # but every state change happens on the calling thread


def test_concurrency_never_exceeds_the_worker_limit():
    live, peak, lock = 0, 0, threading.Lock()

    def work(_):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        threading.Event().wait(0.05)
        with lock:
            live -= 1

    run_parallel(range(9), work, lambda *a: None, workers=3)
    assert 2 <= peak <= 3


def test_errors_are_handed_to_apply_not_raised_and_do_not_stop_the_others():
    seen = {}

    def work(i):
        if i == 1:
            raise RuntimeError("boom")
        return i

    run_parallel(range(3), work, lambda i, r, e: seen.__setitem__(i, (r, type(e).__name__ if e else None)), workers=3)
    assert seen == {0: (0, None), 1: (None, "RuntimeError"), 2: (2, None)}


# ---- the pipeline steps really are concurrent ------------------------------------------------------------
def test_scene_plans_run_concurrently_and_match_the_sequential_result(monkeypatch):
    def respond(prompt, schema):
        return entity_json(p) if schema.__name__ == "EntityPlan" else scene_json(scene_of(prompt), [dec("CHAR_RAVI", adapted=f"d-{scene_of(prompt)}")])

    p = ready_project()
    seq = SceneAwareLLM(respond)
    build_plan(p, seq)
    sequential = {sid: sp.model_dump() for sid, sp in p.plan.scenes.items()}

    monkeypatch.setattr(settings, "llm_concurrency", 4)
    q = ready_project()
    par = SceneAwareLLM(respond, barrier_schema="ScenePlan", parties=4)  # all four scenes must be in flight at once
    from app.storage import JsonCache
    build_plan(q, par, cache=JsonCache(settings.workspace / "other-cache"))
    assert q.plan.failed_scenes == {} and q.status == ProjectStatus.PLAN_READY
    assert {sid: sp.model_dump() for sid, sp in q.plan.scenes.items()} == sequential  # same answer, faster
    assert [d.id for d in q.decisions] == [d.id for d in p.decisions]  # decision ids stay deterministic


def test_the_cast_plan_still_comes_first_because_scenes_depend_on_its_names(monkeypatch):
    monkeypatch.setattr(settings, "llm_concurrency", 4)
    p = ready_project()
    order = []

    def respond(prompt, schema):
        order.append(schema.__name__)
        return entity_json(p) if schema.__name__ == "EntityPlan" else scene_json(scene_of(prompt))

    build_plan(p, SceneAwareLLM(respond))
    assert order[0] == "EntityPlan" and order.count("ScenePlan") == 4


def test_rewrite_scenes_run_concurrently(monkeypatch):
    p = approved_project()  # built single-threaded: its scripted model is order-dependent
    monkeypatch.setattr(settings, "llm_concurrency", 4)
    llm = SceneAwareLLM(lambda prompt, schema: rewrite_json(p, scene_of(prompt)), barrier_schema="SceneRewrite", parties=4)
    rewrite_screenplay(p, llm)
    assert p.rewrite_failed == {} and p.status == ProjectStatus.REWRITTEN
    assert [a.source_scene_id for a in p.adapted_scenes] == SCENES  # committed in story order regardless of finish order


def test_extraction_runs_concurrently(monkeypatch):
    from tests.test_extraction import TEXT, ok
    monkeypatch.setattr(settings, "llm_concurrency", 3)
    from app.models import Project
    p = Project()
    prepare_source(p, TEXT)

    def respond(prompt, schema):
        n = int(re.search(r"This is scene (\d+) of", prompt).group(1))
        return ok(n, ("RAVI",) if n == 2 else ("MEERA", "RAVI"), props=("LETTER",) if n < 3 else ())

    llm = SceneAwareLLM(respond, barrier_schema="SceneExtraction", parties=3)
    run_extraction(p, llm)
    assert p.status == ProjectStatus.EXTRACTED and all(s.extraction and not s.error for s in p.source_scenes)


def test_one_failing_scene_under_concurrency_does_not_lose_the_others(monkeypatch):
    monkeypatch.setattr(settings, "llm_concurrency", 4)
    p = ready_project()

    def respond(prompt, schema):
        if schema.__name__ == "EntityPlan":
            return entity_json(p)
        if scene_of(prompt) == "SC03":
            raise RuntimeError("model down")
        return scene_json(scene_of(prompt))

    build_plan(p, SceneAwareLLM(respond))
    assert set(p.plan.scenes) == {"SC01", "SC02", "SC04"} and "SC03" in p.plan.failed_scenes
    assert p.status == ProjectStatus.NORMALIZED  # incomplete: does not advance
    retry = SceneAwareLLM(lambda prompt, schema: scene_json(scene_of(prompt)))
    build_plan(p, retry)
    assert retry.calls == ["ScenePlan"] and p.status == ProjectStatus.PLAN_READY  # only the failed scene is redone


# ---- progress ---------------------------------------------------------------------------------------------
def test_progress_is_reported_from_the_calling_thread_and_reaches_the_total(monkeypatch):
    monkeypatch.setattr(settings, "llm_concurrency", 4)
    p = ready_project()
    events, threads = [], set()

    def on_progress(label, done, total):
        events.append((label, done, total))
        threads.add(threading.get_ident())

    build_plan(p, SceneAwareLLM(lambda prompt, schema: entity_json(p) if schema.__name__ == "EntityPlan" else scene_json(scene_of(prompt))),
               on_progress=on_progress)
    assert threads == {threading.get_ident()}  # so it is safe to save the project inside the callback
    assert events[0] == ("Planning the cast, costumes and places", 0, 5) and events[-1] == ("Planning scenes", 5, 5)
    assert [d for _, d, _ in events] == sorted(d for _, d, _ in events)  # monotonic


# ---- budgets enforced in code -----------------------------------------------------------------------------
def test_output_budgets_are_enforced_by_code_not_by_asking_nicely():
    p = ready_project()
    many = [dec(adapted=f"cast-{i}", original=f"o{i}") for i in range(30)]
    scene = lambda sid: scene_json(sid, [dec(adapted=f"s-{i}", original=f"o{i}") for i in range(20)],
                                   gestures=[f"g{i}" for i in range(12)], food=[f"f{i}" for i in range(12)])
    llm = SceneAwareLLM(lambda prompt, schema: entity_json(p, decisions=many) if schema.__name__ == "EntityPlan" else scene(scene_of(prompt)))
    build_plan(p, llm)
    assert len(p.plan.entities.decisions) == MAX_ENTITY_DECISIONS
    assert all(len(sp.decisions) == MAX_SCENE_DECISIONS and len(sp.gestures) == MAX_LIST_ITEMS and len(sp.food) == MAX_LIST_ITEMS
               for sp in p.plan.scenes.values())
    assert p.plan.entities.decisions[0].adapted == "cast-0"  # the model's first (most important) items are the ones kept
    assert len(p.decisions) == MAX_ENTITY_DECISIONS + 4 * MAX_SCENE_DECISIONS


def test_the_capped_answer_is_what_gets_cached():
    p = ready_project()
    many = [dec(adapted=f"c{i}", original=f"o{i}") for i in range(30)]
    build_plan(p, SceneAwareLLM(lambda prompt, schema: entity_json(p, decisions=many) if schema.__name__ == "EntityPlan" else scene_json(scene_of(prompt))))
    q = ready_project()
    again = SceneAwareLLM(lambda *a: (_ for _ in ()).throw(AssertionError("must come from the cache")))
    build_plan(q, again)
    assert again.calls == [] and len(q.plan.entities.decisions) == MAX_ENTITY_DECISIONS


# ---- telemetry --------------------------------------------------------------------------------------------
def test_metrics_summarise_a_stretch_of_work():
    m = Metrics()
    m.record("gpt-5", 30.0, 5000, 2700, 700)
    mark = m.mark()
    m.record("gpt-5", 31.0, 5000, 2600, 0)
    m.record("gpt-4.1-mini", 10.0, 2000, 800, 0)
    m.record("gpt-5", 5.0, ok=False)
    s = m.summary(since=mark)
    assert s["calls"] == 3 and s["errors"] == 1 and s["model_seconds"] == 46.0
    assert s["completion_tokens"] == 3400 and s["by_model"]["gpt-5"]["calls"] == 2
    assert m.summary()["reasoning_tokens"] == 700


def test_azure_client_records_time_tokens_and_reasoning_for_every_call():
    from app.llm.metrics import METRICS
    from app.models import SceneExtraction
    from tests.test_azure_and_factory import _azure, _resp

    usage = type("U", (), {"prompt_tokens": 120, "completion_tokens": 60,
                           "completion_tokens_details": type("D", (), {"reasoning_tokens": 25})()})()
    resp = _resp("{}")
    resp.usage = usage
    c, _ = _azure(lambda kw: resp, "gpt-5")
    mark = METRICS.mark()
    c.complete_json("s", "p", SceneExtraction)
    s = METRICS.summary(since=mark)
    assert s["calls"] == 1 and s["prompt_tokens"] == 120 and s["completion_tokens"] == 60 and s["reasoning_tokens"] == 25
    assert c.last_usage["reasoning"] == 25


def test_a_failed_call_is_counted_as_an_error():
    import httpx
    import openai
    from app.llm.metrics import METRICS
    from app.models import SceneExtraction
    from tests.test_azure_and_factory import _azure

    def boom(kw):
        raise openai.AuthenticationError("no", response=httpx.Response(401, request=httpx.Request("POST", "http://x")), body=None)

    c, _ = _azure(boom)
    mark = METRICS.mark()
    with pytest.raises(openai.AuthenticationError):
        c.complete_json("s", "p", SceneExtraction)
    assert METRICS.summary(since=mark)["errors"] == 1
