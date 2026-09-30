"""Groq client. Groq has no schema-constrained output for all models, so the schema is
embedded in the prompt and validated by generate_structured(). One model per client."""
import json

from pydantic import BaseModel

from app.config import settings

from .base import call_with_retry


class GroqClient:
    name = "groq"

    def __init__(self, model: str, api_key: str | None = None, timeout: float | None = None):
        from groq import Groq

        self.model = model
        self._client = Groq(
            api_key=api_key or settings.groq_api_key, timeout=timeout or settings.llm_request_timeout, max_retries=0
        )

    @staticmethod
    def _transient(e: Exception) -> bool:
        import groq

        return isinstance(e, (groq.RateLimitError, groq.APIConnectionError, groq.InternalServerError))

    def complete_json(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        sys = f"{system}\n\nReturn ONLY a JSON object matching this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
        resp = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": sys}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            ),
            self._transient,
        )
        return resp.choices[0].message.content or ""
