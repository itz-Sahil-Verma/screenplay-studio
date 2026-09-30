"""A deterministic image provider for tests: a real, decodable PNG whose look depends on the prompt and references."""
import hashlib
import io
import threading

from PIL import Image, ImageDraw


class FakeImageClient:
    name = "fake"
    model = "fake-image"
    max_references = 8

    def __init__(self, fail_for: set[str] | None = None):
        self.fail_for = fail_for or set()  # substrings of prompts that should fail
        self.calls: list[dict] = []
        self.lock = threading.Lock()

    def _png(self, seed: str, size: str, refs: int = 0) -> bytes:
        w, h = (int(x) for x in size.split("x"))
        w, h = w // 8, h // 8  # tiny: fast tests
        digest = hashlib.sha256(seed.encode()).digest()
        img = Image.new("RGB", (w, h), (digest[0], digest[1], digest[2]))
        d = ImageDraw.Draw(img)
        for i in range(6):  # some structure so the image is not blank
            d.rectangle([digest[3 + i] % w // 2, digest[9 + i] % h // 2, w // 2 + digest[15 + i] % (w // 2), h // 2 + digest[21 + i] % (h // 2)], outline=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def _record(self, kind, prompt, size, references=()):
        with self.lock:
            self.calls.append({"kind": kind, "prompt": prompt, "size": size, "refs": [hashlib.sha256(r).hexdigest()[:8] for r in references]})
        if any(s in prompt for s in self.fail_for):
            raise RuntimeError("fake image failure")

    def generate(self, prompt: str, size: str) -> bytes:
        self._record("generate", prompt, size)
        return self._png(prompt, size)

    def edit(self, prompt: str, references: list[bytes], size: str) -> bytes:
        self._record("edit", prompt, size, references)
        return self._png(prompt + "|" + "|".join(hashlib.sha256(r).hexdigest() for r in references), size, len(references))
