"""Azure OpenAI / Foundry image client (gpt-image-1 family) through the OpenAI v1 API.

generate() is text to image. edit() sends the approved reference images together with the prompt, which is how a
costume sheet or a keyframe keeps the SAME person: consistency comes from conditioning on real reference images,
not from hoping the words match."""
import base64

from app.config import settings
from app.llm.azure import base_url
from app.llm.base import call_with_retry
from app.llm.metrics import METRICS

from .base import ImageError

import time


def image_base_url(endpoint: str) -> str:
    """The images API lives on the resource, not on a Foundry *project* endpoint (…/api/projects/<name>), which
    routes chat but answers 404 for images. Accept either form as pasted and return the resource's v1 URL."""
    e = endpoint.strip().rstrip("/").split("/api/projects/")[0]
    return base_url(e)


class AzureImageClient:
    name = "azure"
    max_references = 16  # the OpenAI images edit endpoint accepts up to 16 input images

    def __init__(self, deployment: str | None = None, endpoint: str | None = None, api_key: str | None = None):
        from openai import OpenAI

        self.model = deployment or settings.azure_deployment_image
        if not self.model:
            raise ImageError("no image model configured: set AZURE_DEPLOYMENT_IMAGE in .env to your Foundry image deployment name")
        self._client = OpenAI(
            base_url=image_base_url(endpoint or settings.azure_openai_endpoint),
            api_key=api_key or settings.azure_openai_api_key,
            timeout=settings.image_request_timeout,
            max_retries=0,
        )

    @staticmethod
    def _transient(e: Exception) -> bool:
        import openai

        return isinstance(e, (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError))

    def _run(self, call) -> bytes:
        import openai

        started = time.perf_counter()
        try:
            resp = call_with_retry(call, self._transient, attempts=4, delay=15.0)
        except openai.NotFoundError as e:
            METRICS.record(self.model, time.perf_counter() - started, ok=False)
            raise ImageError(f"Azure image deployment {self.model!r} not found. Check AZURE_DEPLOYMENT_IMAGE in .env matches the name in Foundry.") from e
        except openai.BadRequestError as e:
            METRICS.record(self.model, time.perf_counter() - started, ok=False)
            raise ImageError(f"the image model rejected the request: {str(e)[:300]}") from e
        except Exception:
            METRICS.record(self.model, time.perf_counter() - started, ok=False)
            raise
        METRICS.record(self.model, time.perf_counter() - started)
        item = resp.data[0]
        if getattr(item, "b64_json", None):
            return base64.b64decode(item.b64_json)
        raise ImageError("the image model returned no image data (it may have been blocked by a content filter)")

    def generate(self, prompt: str, size: str) -> bytes:
        return self._run(lambda: self._client.images.generate(model=self.model, prompt=prompt, size=size, quality=settings.image_quality, n=1))

    def edit(self, prompt: str, references: list[bytes], size: str) -> bytes:
        files = [(f"reference_{i + 1}.png", ref, "image/png") for i, ref in enumerate(references)]
        extra = {"input_fidelity": settings.image_input_fidelity} if settings.image_input_fidelity else {}
        return self._run(lambda: self._client.images.edit(model=self.model, image=files, prompt=prompt, size=size, quality=settings.image_quality, n=1, **extra))
