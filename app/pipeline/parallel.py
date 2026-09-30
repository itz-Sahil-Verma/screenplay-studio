"""Bounded concurrent execution with a single-threaded commit point.

The pattern that keeps concurrency simple and safe:
  * `work(item)` runs in a worker thread. It may read shared state but must not change it: it returns a result or raises.
  * `apply(item, result, error)` runs on the CALLING thread, one item at a time, as each finishes. All shared state
    (the project, the saved file, progress) is changed only here, so no locks are needed and no update can interleave.
With `workers <= 1` everything runs inline and in order, which makes runs deterministic (used by tests and debugging).
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def run_parallel(
    items: Iterable[T],
    work: Callable[[T], R],
    apply: Callable[[T, R | None, Exception | None], None],
    workers: int,
) -> None:
    items = list(items)

    def call(item: T) -> tuple[T, R | None, Exception | None]:
        try:
            return item, work(item), None
        except Exception as e:  # noqa: BLE001: handed to apply(), never lost or raised in a thread
            return item, None, e

    if workers <= 1 or len(items) <= 1:
        for item in items:
            apply(*call(item))
        return
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        for future in as_completed([pool.submit(call, item) for item in items]):
            apply(*future.result())
