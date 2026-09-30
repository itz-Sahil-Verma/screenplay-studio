"""Image provider abstraction. The pipeline depends on this, never on a vendor SDK, exactly like the text models."""
from typing import Protocol


class ImageError(Exception):
    """An image could not be produced (after retries)."""


class ImageClient(Protocol):
    name: str
    model: str
    max_references: int  # how many reference images one request may carry

    def generate(self, prompt: str, size: str) -> bytes:
        """Text to image. Returns PNG bytes."""
        ...

    def edit(self, prompt: str, references: list[bytes], size: str) -> bytes:
        """Image(s) + text to image: the way later images keep the face, body and clothes of an approved reference."""
        ...
