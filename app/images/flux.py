"""FLUX.2 (Black Forest Labs) on Microsoft Foundry, through the BFL provider API.

Documented format (learn.microsoft.com "Deploy and use FLUX models in Microsoft Foundry"):
  POST https://<resource>.api.cognitive.microsoft.com/providers/blackforestlabs/v1/<flux-2-pro|flux-2-flex>?api-version=preview
  Authorization: Bearer <api key>
  body {model, prompt, width, height, output_format, input_image, input_image_2, ...}; reference images are base64 fields,
  up to 8 for FLUX.2-pro and 10 for FLUX.2-flex. The image comes back as data[0].b64_json (or a URL).
"""
import base64
import time
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.llm.base import call_with_retry
from app.llm.metrics import METRICS

from .base import ImageError

PATHS = {"FLUX.2-pro": "flux-2-pro", "FLUX.2-flex": "flux-2-flex"}
MAX_REFS = {"FLUX.2-pro": 8, "FLUX.2-flex": 10}


def flux_endpoint() -> str:
    """The BFL host. Uses AZURE_FLUX_ENDPOINT if set, else derives it from the resource name in AZURE_OPENAI_ENDPOINT."""
    if settings.azure_flux_endpoint:
        return settings.azure_flux_endpoint.rstrip("/")
    name = (urlparse(settings.azure_openai_endpoint).hostname or "").split(".")[0]
    if not name:
        raise ImageError("cannot work out the FLUX endpoint: set AZURE_FLUX_ENDPOINT (https://<resource>.api.cognitive.microsoft.com) in .env")
    return f"https://{name}.api.cognitive.microsoft.com"


class AzureFluxClient:
    name = "azure_flux"

    def __init__(self, model: str | None = None, endpoint: str | None = None, api_key: str | None = None, http: httpx.Client | None = None):
        self.model = model or settings.azure_flux_model
        if self.model not in PATHS:
            raise ImageError(f"AZURE_FLUX_MODEL must be one of {sorted(PATHS)}, not {self.model!r}")
        self.max_references = MAX_REFS[self.model]
        self._url = f"{(endpoint or flux_endpoint()).rstrip('/')}/providers/blackforestlabs/v1/{PATHS[self.model]}?api-version=preview"
        self._key = api_key or settings.azure_openai_api_key
        self._http = http or httpx.Client(timeout=settings.image_request_timeout)

    @staticmethod
    def _transient(e: Exception) -> bool:
        if isinstance(e, httpx.HTTPStatusError):
            return e.response.status_code in (429, 500, 502, 503, 504)
        return isinstance(e, (httpx.TimeoutException, httpx.TransportError))

    def _post(self, body: dict) -> bytes:
        def call():
            r = self._http.post(self._url, json=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"})
            r.raise_for_status()
            return r.json()

        started = time.perf_counter()
        try:
            data = call_with_retry(call, self._transient, attempts=2, delay=5.0)
        except httpx.HTTPStatusError as e:
            METRICS.record(self.model, time.perf_counter() - started, ok=False)
            code, detail = e.response.status_code, e.response.text[:300]
            if code == 404:
                raise ImageError(f"FLUX endpoint not found ({self._url}). Check that {self.model} is deployed and AZURE_FLUX_ENDPOINT / AZURE_FLUX_MODEL in .env are right.") from e
            if code in (401, 403):
                raise ImageError(f"FLUX rejected the credentials ({code}). Check AZURE_OPENAI_API_KEY belongs to the resource that hosts {self.model}.") from e
            raise ImageError(f"FLUX rejected the request ({code}): {detail}") from e
        except Exception:
            METRICS.record(self.model, time.perf_counter() - started, ok=False)
            raise
        METRICS.record(self.model, time.perf_counter() - started)
        item = (data.get("data") or [{}])[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            return self._http.get(item["url"]).content
        raise ImageError("FLUX returned no image (it may have been blocked by a safety filter)")

    def _body(self, prompt: str, size: str, references: list[bytes]) -> dict:
        width, height = (int(x) for x in size.split("x"))
        body = {"model": self.model, "prompt": prompt, "width": width, "height": height, "output_format": "png"}
        if len(references) > self.max_references:
            raise ImageError(f"{self.model} accepts at most {self.max_references} reference images, got {len(references)}")
        for i, ref in enumerate(references):
            body["input_image" if i == 0 else f"input_image_{i + 1}"] = base64.b64encode(ref).decode()
        return body

    def generate(self, prompt: str, size: str) -> bytes:
        return self._post(self._body(prompt, size, []))

    def edit(self, prompt: str, references: list[bytes], size: str) -> bytes:
        return self._post(self._body(prompt, size, references))
