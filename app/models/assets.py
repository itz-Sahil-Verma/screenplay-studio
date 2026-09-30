"""Generated image assets and the spec needed to reproduce each one."""
import hashlib
import json

from pydantic import BaseModel, Field

from .common import AssetKind, AssetStatus


def spec_hash(spec: dict) -> str:
    """Stable hash of a generation spec. If the hash changes, the asset is stale."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


class Asset(BaseModel):
    id: str  # ASSET_CHARREF_CHAR_AMAR
    kind: AssetKind
    entity_id: str  # CHAR_* / COST_* / SC*
    status: AssetStatus = AssetStatus.PENDING
    model: str = ""
    prompt: str = ""
    spec: dict = Field(default_factory=dict)  # structured spec assembled from records
    spec_hash: str = ""
    reference_asset_ids: list[str] = Field(default_factory=list)  # approved refs used
    path: str = ""  # file relative to the project folder
    attempts: int = 0
    error: str = ""
    problems: list[str] = Field(default_factory=list)  # what the automatic checks found wrong with the image
    seconds: float = 0.0  # how long the last generation took
    size: str = ""  # e.g. "1024x1536"
