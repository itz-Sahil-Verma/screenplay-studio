"""Builds the LLM client for a pipeline step. ONE provider, chosen by LLM_PROVIDER.

There is deliberately no fallback between providers or models: what is configured is what
runs, and a failure is reported as-is. To switch provider, change LLM_PROVIDER in .env
(and add that provider's key).
"""
from app.config import settings

from .base import LLMClient, LLMError

PROVIDERS = ("azure", "gemini", "groq")
STEPS = ("extract", "adapt")  # extract = cheap/structured, adapt = quality-critical rewrite


def _require(provider: str, **needed: str) -> None:
    missing = [name for name, value in needed.items() if not value]
    if missing:
        raise LLMError(f"LLM_PROVIDER={provider} but these are empty in .env: {', '.join(missing)}")


def get_client(step: str = "extract") -> LLMClient:
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}; expected one of {STEPS}")
    provider = settings.llm_provider.strip().lower()
    timeout = settings.llm_request_timeout_adapt if step == "adapt" else settings.llm_request_timeout

    if provider == "azure":
        _require(
            provider,
            AZURE_OPENAI_ENDPOINT=settings.azure_openai_endpoint,
            AZURE_OPENAI_API_KEY=settings.azure_openai_api_key,
            **{f"AZURE_DEPLOYMENT_{step.upper()}": getattr(settings, f"azure_deployment_{step}")},
        )
        from .azure import AzureOpenAIClient

        return AzureOpenAIClient(getattr(settings, f"azure_deployment_{step}"), timeout=timeout)
    if provider == "gemini":
        _require(provider, GEMINI_API_KEY=settings.gemini_api_key)
        from .gemini import GeminiClient

        return GeminiClient(getattr(settings, f"gemini_model_{step}"), timeout=timeout)
    if provider == "groq":
        _require(provider, GROQ_API_KEY=settings.groq_api_key)
        from .groq_client import GroqClient

        return GroqClient(getattr(settings, f"groq_model_{step}"), timeout=timeout)
    raise LLMError(f"unknown LLM_PROVIDER {settings.llm_provider!r}; use one of {PROVIDERS}")
