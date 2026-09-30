"""Shared enums used across all models."""
from enum import Enum


class IntExt(str, Enum):
    INT = "INT"
    EXT = "EXT"
    INT_EXT = "INT/EXT"


class Setting(str, Enum):
    RURAL = "rural"
    URBAN = "urban"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"  # blocks image generation until fixed or acknowledged


class StateChangeKind(str, Enum):
    PROP_GAIN = "prop_gain"
    PROP_LOSS = "prop_loss"
    PROP_TRANSFER = "prop_transfer"
    INJURY_GAIN = "injury_gain"
    INJURY_HEAL = "injury_heal"
    KNOWLEDGE_GAIN = "knowledge_gain"
    COSTUME_CHANGE = "costume_change"
    RELATIONSHIP_CHANGE = "relationship_change"


class Dimension(str, Enum):
    """What an adaptation decision is about (mirrors the brief's table)."""

    VERBAL = "verbal"
    NON_VERBAL = "non_verbal"
    CHARACTER = "character"
    VISUAL_WORLD = "visual_world"
    STORY_WORLD = "story_world"


class ReviewStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class LineKind(str, Enum):
    DIALOGUE = "dialogue"
    ACTION = "action"
    GESTURE = "gesture"
    SOUND = "sound"


class AssetKind(str, Enum):
    CHARACTER_REF = "character_ref"
    COSTUME_SHEET = "costume_sheet"
    SCENE_KEYFRAME = "scene_keyframe"


class AssetStatus(str, Enum):
    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"
    STALE = "stale"  # a source record changed after generation


class ProjectStatus(str, Enum):
    CREATED = "created"  # source uploaded
    EXTRACTED = "extracted"  # LLM produced structured records
    NORMALIZED = "normalized"  # aliases merged, duplicates removed
    PLAN_READY = "plan_ready"  # adaptation plan awaiting review
    APPROVED = "approved"  # user approved characters, plan, costumes
    REWRITTEN = "rewritten"  # adapted screenplay produced
    GENERATED = "generated"  # images produced
    EXPORTED = "exported"
