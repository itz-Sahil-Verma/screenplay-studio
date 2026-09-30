"""Per-call telemetry, so optimisation is driven by measurements and not by guesses.

Every model call records how long it took and how many tokens it used (including hidden reasoning tokens).
`METRICS.mark()` + `METRICS.summary(since=mark)` give the cost of any stretch of work, e.g. one pipeline stage.
Thread-safe: calls are recorded from worker threads.
"""
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class CallRecord:
    model: str
    seconds: float
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    ok: bool


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[CallRecord] = []

    def record(self, model: str, seconds: float, prompt: int = 0, completion: int = 0, reasoning: int = 0, ok: bool = True) -> None:
        with self._lock:
            self._calls.append(CallRecord(model, seconds, prompt, completion, reasoning, ok))

    def mark(self) -> int:
        with self._lock:
            return len(self._calls)

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()

    def summary(self, since: int = 0) -> dict:
        """Totals for the calls after `since`. `model_seconds` is summed call time: with concurrency it exceeds wall time,
        and the ratio between the two is the parallel speed-up."""
        with self._lock:
            calls = self._calls[since:]
        by_model: dict[str, dict] = {}
        for c in calls:
            m = by_model.setdefault(c.model, {"calls": 0, "seconds": 0.0, "completion_tokens": 0})
            m["calls"] += 1
            m["seconds"] += c.seconds
            m["completion_tokens"] += c.completion_tokens
        return {
            "calls": len(calls),
            "errors": sum(not c.ok for c in calls),
            "model_seconds": round(sum(c.seconds for c in calls), 1),
            "prompt_tokens": sum(c.prompt_tokens for c in calls),
            "completion_tokens": sum(c.completion_tokens for c in calls),
            "reasoning_tokens": sum(c.reasoning_tokens for c in calls),
            "by_model": {k: {**v, "seconds": round(v["seconds"], 1)} for k, v in by_model.items()},
        }


METRICS = Metrics()
