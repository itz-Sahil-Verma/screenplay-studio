"""Builds the image client. ONE provider, chosen by IMAGE_PROVIDER, and no fallback (same rule as the text models)."""
from app.config import settings

from .base import ImageClient, ImageError


def get_image_client() -> ImageClient:
    provider = settings.image_provider.strip().lower()
    if provider == "azure":
        missing = [n for n, v in (("AZURE_OPENAI_ENDPOINT", settings.azure_openai_endpoint), ("AZURE_OPENAI_API_KEY", settings.azure_openai_api_key),
                                  ("AZURE_DEPLOYMENT_IMAGE", settings.azure_deployment_image)) if not v]
        if missing:
            raise ImageError(f"IMAGE_PROVIDER=azure but these are empty in .env: {', '.join(missing)}")
        from .azure import AzureImageClient

        return AzureImageClient()
    if provider == "azure_flux":
        missing = [n for n, v in (("AZURE_OPENAI_API_KEY", settings.azure_openai_api_key), ("AZURE_FLUX_MODEL", settings.azure_flux_model)) if not v]
        if missing:
            raise ImageError(f"IMAGE_PROVIDER=azure_flux but these are empty in .env: {', '.join(missing)}")
        from .flux import AzureFluxClient

        return AzureFluxClient()
    raise ImageError(f"unknown IMAGE_PROVIDER {settings.image_provider!r}; use 'azure' (gpt-image-*) or 'azure_flux' (FLUX.2)")
