"""Central settings, loaded once from environment / .env."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    max_upload_mb: int = 10  # a 3-5 page screenplay is well under 1 MB
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # one switch: azure | gemini | groq
    llm_provider: str = "azure"
    llm_concurrency: int = 3  # model calls in flight at once for independent scenes (1 = strictly sequential)
    llm_request_timeout: float = 60.0  # seconds, per request (extraction)
    llm_request_timeout_adapt: float = 240.0  # the plan and rewrite produce long outputs

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_deployment_extract: str = "gpt-4.1-mini"
    azure_deployment_adapt: str = "gpt-5"
    azure_reasoning_deployments: str = "gpt-5"  # exact deployment names, comma-separated
    azure_reasoning_effort: str = "low"

    gemini_api_key: str = ""
    gemini_model_extract: str = "gemini-3.6-flash"
    gemini_model_adapt: str = "gemini-3.6-flash"

    groq_api_key: str = ""
    groq_model_extract: str = "llama-3.3-70b-versatile"
    groq_model_adapt: str = "llama-3.3-70b-versatile"

    # images: ONE provider switch, like the text models (no fallback). Only azure is implemented.
    image_provider: str = "azure"  # azure (gpt-image-*) | azure_flux (FLUX.2)
    azure_deployment_image: str = ""  # e.g. a gpt-image-1 deployment name from Foundry
    # FLUX.2 (Black Forest Labs) on Foundry uses its own API: IMAGE_PROVIDER=azure_flux
    azure_flux_model: str = "FLUX.2-pro"  # model id: FLUX.2-pro or FLUX.2-flex
    azure_flux_endpoint: str = ""  # default: https://<resource>.api.cognitive.microsoft.com, derived from AZURE_OPENAI_ENDPOINT
    image_quality: str = "medium"  # low | medium | high: cost and latency vs detail
    image_input_fidelity: str = ""  # "high" asks the model to preserve faces from reference images (if your deployment supports it)
    image_concurrency: int = 2  # images generated at once (they are slow and rate-limited)
    image_request_timeout: float = 240.0
    workspace_dir: str = "workspace"
    llm_max_retries: int = 3

    @property
    def workspace(self) -> Path:
        return ROOT / self.workspace_dir


settings = Settings()
