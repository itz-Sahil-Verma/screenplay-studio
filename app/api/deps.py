"""Project storage access with per-project locking, and a small in-memory job runner.

Long stages (extract, normalize, plan) run as background jobs so the HTTP request returns at once.
While a job runs, every mutating endpoint answers 409, so nobody edits a project a job is rewriting.
Reads are always allowed: project files are replaced atomically, so a read never sees a half-written file.
"""
import threading
import time
from contextlib import contextmanager

from app.llm import get_client
from app.models import Project
from app.storage import load_project, save_project

_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()
JOBS: dict[str, dict] = {}  # project id -> {name, state, error, started, finished}
SYNC_JOBS = False  # tests set this so a job finishes before the request returns


def llm_for(step: str):
    """Indirection so tests can supply a scripted model."""
    return get_client(step)


def image_for():
    """Indirection so tests can supply a fake image model."""
    from app.images import get_image_client
    return get_image_client()


class Busy(Exception):
    """A background job is running on this project."""


def _lock(pid: str) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault(pid, threading.Lock())


def read_project(pid: str) -> Project:
    try:
        return load_project(pid)
    except FileNotFoundError as e:
        raise KeyError(f"unknown project {pid!r}") from e


def ensure_idle(pid: str) -> None:
    if JOBS.get(pid, {}).get("state") == "running":
        raise Busy(f"a '{JOBS[pid]['name']}' job is running on this project; wait for it to finish")


@contextmanager
def open_project(pid: str):
    """Load, let the caller mutate, save. Refuses while a job is running."""
    ensure_idle(pid)
    with _lock(pid):
        project = read_project(pid)
        yield project
        save_project(project)


def start_job(pid: str, name: str, fn) -> dict:
    """Run fn(project, report) in the background and save the result. The outcome is visible via JOBS[pid].

    `report(label, done, total)` is how long work says where it is. It updates the job's progress AND saves the
    project, so finished scenes are on disk the moment they finish: a crash, a restart or an impatient reader never
    loses them, and re-running only redoes what is missing. It is called from the job's own thread only."""
    read_project(pid)  # 404 early
    with _GUARD:  # check and claim in one step: a double click must not start (and pay for) the same job twice
        ensure_idle(pid)
        JOBS[pid] = {"name": name, "state": "running", "error": "", "started": time.time(), "finished": None,
                     "progress": "", "done": None, "total": None}

    def run():
        try:
            with _lock(pid):
                project = read_project(pid)

                def report(label: str, done: int, total: int) -> None:
                    JOBS[pid].update(progress=label, done=done, total=total)
                    save_project(project)

                try:
                    fn(project, report)
                finally:
                    save_project(project)  # keep partial progress (e.g. scenes that did extract)
            JOBS[pid].update(state="done")
        except Exception as e:  # noqa: BLE001: the job's failure is reported, never raised into a thread
            JOBS[pid].update(state="failed", error=f"{type(e).__name__}: {str(e)[:500]}")
        finally:
            JOBS[pid]["finished"] = time.time()

    if SYNC_JOBS:
        run()
    else:
        threading.Thread(target=run, daemon=True, name=f"job-{pid}-{name}").start()
    return JOBS[pid]
