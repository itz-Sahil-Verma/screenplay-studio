"""The cultural adaptation plan, as the model proposes it and as the project stores it.

The *Draft/Plan classes are sent to the LLM as schemas, so they use only simple types.
Nothing here is applied to the canonical records until the user approves (Step 9).
"""
from typing import Literal

from pydantic import BaseModel, Field

DimensionName = Literal["verbal", "non_verbal", "character", "visual_world", "story_world"]


class DecisionDraft(BaseModel):
    """One explained cultural choice, exactly as the model wrote it."""

    dimension: DimensionName
    entity_id: str = ""  # CHAR_/COST_/LOC_/PROP_ id (or a scene id) this decision is about
    original: str  # what the source had
    adapted: str  # what it becomes
    reason: str  # why, in terms of the culture and the story
    basis: Literal["pack", "judgment"]  # backed by pack facts, or the model's own creative choice
    fact_ids: list[str] = Field(default_factory=list)  # pack facts relied on
    uncertain: bool = False


class CharacterPlan(BaseModel):
    character_id: str
    name_roman: str
    name_native: str  # in the selected output script
    role_adapted: str = ""  # occupation / family role in the new setting
    speech_register: str = ""  # how they speak: formality, pronouns, humour, rhythm
    appearance: str = ""  # build, face, apparent age
    grooming: str = ""
    address_terms: list[str] = Field(default_factory=list)  # how others address them


class CostumePlan(BaseModel):
    costume_id: str
    garments: str
    fabrics: str = ""
    colours: str = ""
    footwear: str = ""
    jewellery: str = ""
    headwear: str = ""
    grooming: str = ""
    change_reason: str = ""  # a believable story reason, only when the source gives none


class LocationPlan(BaseModel):
    location_id: str
    name_roman: str = ""
    name_native: str = ""
    description: str  # architecture, interiors, landscape


class PropPlan(BaseModel):
    prop_id: str
    name_roman: str
    name_native: str
    description: str = ""


class EntityPlan(BaseModel):
    # ONE season/time of year and era for the whole story, so scenes planned separately still agree
    season_and_period: str = ""
    characters: list[CharacterPlan] = Field(default_factory=list)
    costumes: list[CostumePlan] = Field(default_factory=list)
    locations: list[LocationPlan] = Field(default_factory=list)
    props: list[PropPlan] = Field(default_factory=list)
    decisions: list[DecisionDraft] = Field(default_factory=list)


class ScenePlan(BaseModel):
    scene_id: str
    setting_notes: str = ""  # time, light, weather, atmosphere for this region
    dialogue_notes: str = ""  # how speech differs from a literal translation
    gestures: list[str] = Field(default_factory=list)
    food: list[str] = Field(default_factory=list)
    sound_music: list[str] = Field(default_factory=list)
    rituals: list[str] = Field(default_factory=list)
    decisions: list[DecisionDraft] = Field(default_factory=list)


class AdaptationPlan(BaseModel):
    """What the project stores. `problems` and `failed_scenes` are shown on the review screen."""

    model: str = ""
    entities: EntityPlan | None = None
    scenes: dict[str, ScenePlan] = Field(default_factory=dict)  # scene id -> plan
    failed_scenes: dict[str, str] = Field(default_factory=dict)  # scene id -> error
    problems: list[str] = Field(default_factory=list)  # unresolved verification problems
    stale_scenes: list[str] = Field(default_factory=list)  # planned before a later edit: re-plan before approving
