"""LLM abstraction. Pipeline code depends on this, never on a vendor SDK."""
import logging
import time
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model could not produce a usable answer (after retries)."""


class LLMClient(Protocol):
    name: str

    def complete_json(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        """Return the model's raw JSON text. May raise on network/quota errors."""
        ...


def try_parse(raw: str, schema: type[T]) -> tuple[T | None, str]:
    """Validate raw model text. Returns (object, "") or (None, error message for feedback)."""
    try:
        return schema.model_validate_json(raw), ""
    except ValidationError as e:
        return None, str(e)[:800]


def generate_structured(
    client: LLMClient,
    system: str,
    prompt: str,
    schema: type[T],
    max_retries: int | None = None,
) -> T:
    """Call the model and validate against `schema`.

    `max_retries` is the TOTAL number of model calls (default LLM_MAX_RETRIES). If the JSON
    is invalid, the validation error is fed back so the model can correct itself. Transport
    errors are retried separately, inside the client (call_with_retry).
    """
    max_retries = max_retries or settings.llm_max_retries
    last_error = ""
    for attempt in range(1, max_retries + 1):
        full_prompt = prompt
        if last_error:
            full_prompt += (
                "\n\nYour previous answer was rejected:\n"
                f"{last_error}\nReturn corrected JSON only."
            )
        raw = client.complete_json(system, full_prompt, schema)
        obj, last_error = try_parse(raw, schema)
        if obj is not None:
            return obj
    raise LLMError(f"{client.name}: invalid output after {max_retries} attempts: {last_error}")


def call_with_retry(
    fn: Callable[[], R],
    is_transient: Callable[[Exception], bool],
    attempts: int = 2,
    delay: float = 2.0,
) -> R:
    """Retry the SAME call on transient errors (rate limit, 5xx, timeout). No provider or
    model switching: if it still fails, the error is raised for the caller to record."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if attempt == attempts or not is_transient(e):
                raise
            log.warning("transient error (%s), retry %d/%d", type(e).__name__, attempt, attempts - 1)
            time.sleep(delay)
    raise AssertionError("unreachable")
