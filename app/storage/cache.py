"""Tiny on-disk JSON cache. Used so a scene that was extracted successfully is never paid for
twice. Only verified results are stored, and the key includes the prompt and the model, so
changing either invalidates the entry."""
import hashlib
import json
from pathlib import Path

from app.config import settings


def make_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


class JsonCache:
    def __init__(self, directory: Path):
        self.dir = directory

    def get(self, key: str) -> dict | None:
        f = self.dir / f"{key}.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        except (OSError, json.JSONDecodeError):
            return None  # a corrupt entry is just a miss

    def set(self, key: str, value: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{key}.tmp"
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / f"{key}.json")  # atomic


def default_cache(name: str) -> JsonCache:
    return JsonCache(settings.workspace / "cache" / name)
