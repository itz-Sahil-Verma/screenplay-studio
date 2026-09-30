"""Discovers culture packs and scripts from disk. Adding a culture = dropping a JSON file in packs/."""
import json
from pathlib import Path

from app.models.culture import CulturePack, ScriptInfo

BASE = Path(__file__).parent


def load_scripts(path: Path = BASE / "scripts.json") -> dict[str, ScriptInfo]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {sid: ScriptInfo(id=sid, **v) for sid, v in raw.items()}


def list_packs(packs_dir: Path = BASE / "packs") -> list[CulturePack]:
    packs = [
        CulturePack.model_validate_json(f.read_text(encoding="utf-8"))
        for f in sorted(packs_dir.glob("*.json"))
    ]
    scripts = load_scripts()
    for p in packs:  # fail loudly at load time, not mid-pipeline
        missing = [s for s in [*p.supported_scripts, p.default_script] if s not in scripts]
        if missing:
            raise ValueError(f"pack {p.id} references unknown scripts {missing}")
    return packs


def load_pack(pack_id: str, packs_dir: Path = BASE / "packs") -> CulturePack:
    for p in list_packs(packs_dir):
        if p.id == pack_id:
            return p
    raise KeyError(f"unknown culture pack {pack_id!r}")
