"""Raw, per-scene extraction as the LLM reports it: names as written, no canonical IDs yet.

Step 5 (normalization) merges these into the canonical registry. Keeping the raw
form lets a reviewer see exactly what the model claimed for each scene.
These schemas are sent to the LLM, so they use only simple types.
"""
from pydantic import BaseModel, Field


class MentionedCharacter(BaseModel):
    name: str  # the name exactly as written in the scene, e.g. "RAVI"
    other_names: list[str] = Field(default_factory=list)  # other ways this scene refers to them
    age: str = ""  # as written; empty if not stated
    role: str = ""  # e.g. "mother", "retired schoolteacher"
    relationships: list[str] = Field(default_factory=list)  # e.g. "Anu's brother"
    personality: str = ""
    costume: str = ""  # what they wear in this scene, only if the text says
    emotional_state: str = ""
    enters: bool = False  # arrives during this scene
    exits: bool = False  # leaves during this scene


class MentionedProp(BaseModel):
    name: str
    description: str = ""
    holder_at_start: str = ""  # character name, or "" if unstated
    holder_at_end: str = ""  # who has it when the scene ends; "" if unknown
    note: str = ""  # e.g. "left on the table", "handed to Uncle Hari"


class StateEvent(BaseModel):
    kind: str  # prop_gain | prop_loss | prop_transfer | injury_gain | injury_heal | knowledge_gain | costume_change | relationship_change
    character: str  # name as written
    item: str = ""  # prop, injury, or knowledge
    to_character: str = ""  # for prop_transfer
    note: str = ""


class SceneExtraction(BaseModel):
    scene_number: int
    int_ext: str = ""  # INT | EXT | INT/EXT
    location: str = ""  # main place, e.g. "family home"
    sub_location: str = ""  # e.g. "kitchen"
    time: str = ""
    day: str = ""
    weather: str = ""
    mood: str = ""
    summary: str = ""  # 1-2 sentences
    dramatic_purpose: str = ""
    emotional_change: str = ""
    characters: list[MentionedCharacter] = Field(default_factory=list)
    props: list[MentionedProp] = Field(default_factory=list)
    events: list[StateEvent] = Field(default_factory=list)
    set_dressing: list[str] = Field(default_factory=list)
    food: list[str] = Field(default_factory=list)
    vehicles: list[str] = Field(default_factory=list)
    animals: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)
    rituals: list[str] = Field(default_factory=list)
    gestures: list[str] = Field(default_factory=list)
    sound_music: list[str] = Field(default_factory=list)


class SourceScene(BaseModel):
    """One scene of the source screenplay plus what was extracted from it."""

    number: int
    heading: str = ""
    text: str
    extraction: SceneExtraction | None = None
    error: str = ""  # set when extraction failed; retry just this scene
    problems: list[str] = Field(default_factory=list)  # unresolved verification problems (replaced each attempt)
