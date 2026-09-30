"""Gemini client (google-genai SDK). One model per client."""
from pydantic import BaseModel

from app.config import settings

from .base import LLMError, call_with_retry

TRANSIENT_CODES = (429, 500, 502, 503, 504)


class GeminiClient:
    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None, timeout: float | None = None):
        from google import genai
        from google.genai import types

        self.model = model
        self._client = genai.Client(
            api_key=api_key or settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=int((timeout or settings.llm_request_timeout) * 1000)),
        )

    @staticmethod
    def _transient(e: Exception) -> bool:
        from google.genai import errors

        return isinstance(e, errors.APIError) and e.code in TRANSIENT_CODES

    def complete_json(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            resp = call_with_retry(
                lambda: self._client.models.generate_content(model=self.model, contents=prompt, config=config),
                self._transient,
            )
        except errors.APIError as e:
            if e.code == 404:
                raise LLMError(
                    f"Gemini model {self.model!r} is not available to this key. "
                    "Set GEMINI_MODEL_EXTRACT / GEMINI_MODEL_ADAPT in .env to a model you can use."
                ) from e
            raise
        if not resp.text:
            raise LLMError("Gemini returned an empty response (possibly blocked by safety filters)")
        return resp.text
