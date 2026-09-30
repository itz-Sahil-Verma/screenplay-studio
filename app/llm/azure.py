"""Azure OpenAI / Foundry client (OpenAI v1 API on an Azure resource). One deployment per client.

Reasoning models (GPT-5, o-series) reject `temperature`, so they get `reasoning_effort`.
"""
import json
import logging
import time

from pydantic import BaseModel

from app.config import settings

from .base import LLMError, call_with_retry
from .metrics import METRICS

log = logging.getLogger(__name__)


def base_url(endpoint: str) -> str:
    """Accept the endpoint as pasted from the portal and return the v1 API base URL."""
    e = endpoint.strip().rstrip("/")
    for suffix in ("/openai/v1", "/openai"):
        if e.endswith(suffix):
            e = e[: -len(suffix)]
    return f"{e}/openai/v1/"


def is_reasoning(deployment: str) -> bool:
    """Exact match against AZURE_REASONING_DEPLOYMENTS (no substring guessing)."""
    names = {n.strip().lower() for n in settings.azure_reasoning_deployments.split(",") if n.strip()}
    return deployment.strip().lower() in names


class AzureOpenAIClient:
    name = "azure"

    def __init__(self, deployment: str, endpoint: str | None = None, api_key: str | None = None,
                 timeout: float | None = None):
        from openai import OpenAI

        self.deployment = deployment
        self._client = OpenAI(
            base_url=base_url(endpoint or settings.azure_openai_endpoint),
            api_key=api_key or settings.azure_openai_api_key,
            timeout=timeout or settings.llm_request_timeout,
            max_retries=0,  # bounded waits: retries are handled by call_with_retry
        )
        self.last_usage: dict = {}

    @staticmethod
    def _transient(e: Exception) -> bool:
        import openai

        return isinstance(
            e,
            (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError),
        )

    def complete_json(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        import openai

        sys = f"{system}\n\nReturn ONLY a JSON object matching this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
        kwargs = dict(
            model=self.deployment,
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        if is_reasoning(self.deployment):
            kwargs["reasoning_effort"] = settings.azure_reasoning_effort
        else:
            kwargs["temperature"] = 0.2
        started = time.perf_counter()
        try:
            resp = call_with_retry(lambda: self._client.chat.completions.create(**kwargs), self._transient)
        except openai.BadRequestError as e:
            METRICS.record(self.deployment, time.perf_counter() - started, ok=False)
            msg = str(e).lower()
            if "temperature" in msg:
                raise LLMError(
                    f"Deployment {self.deployment!r} rejected 'temperature': it is a reasoning model. "
                    "Add its name to AZURE_REASONING_DEPLOYMENTS in .env."
                ) from e
            if "reasoning" in msg:
                raise LLMError(
                    f"Deployment {self.deployment!r} rejected 'reasoning_effort': it is not a reasoning "
                    "model. Remove its name from AZURE_REASONING_DEPLOYMENTS in .env."
                ) from e
            raise
        except openai.NotFoundError as e:
            METRICS.record(self.deployment, time.perf_counter() - started, ok=False)
            raise LLMError(
                f"Azure deployment {self.deployment!r} not found. Check AZURE_DEPLOYMENT_* in .env "
                "matches the deployment name in Foundry."
            ) from e
        except Exception:
            METRICS.record(self.deployment, time.perf_counter() - started, ok=False)  # timeouts, 429s that outlasted the retry, ...
            raise
        seconds = time.perf_counter() - started
        u = getattr(resp, "usage", None)
        reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        self.last_usage = {"prompt": getattr(u, "prompt_tokens", 0), "completion": getattr(u, "completion_tokens", 0), "reasoning": reasoning}
        METRICS.record(self.deployment, seconds, self.last_usage["prompt"], self.last_usage["completion"], reasoning)
        log.info("%s: %.1fs, %d in / %d out tokens (%d reasoning)", self.deployment, seconds, self.last_usage["prompt"], self.last_usage["completion"], reasoning)
        text = resp.choices[0].message.content or ""
        if not text:
            raise LLMError("Azure returned an empty response (filtered or out of tokens)")
        return text
