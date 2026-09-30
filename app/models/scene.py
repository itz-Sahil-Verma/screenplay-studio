"""Scene records and the state changes that continuity tracking runs on."""
from pydantic import BaseModel, Field

from .common import IntExt, Severity, StateChangeKind


class StateChange(BaseModel):
    """Something that changes for a character or prop during a scene."""

    kind: StateChangeKind
    character_id: str
    item: str = ""  # prop id, injury text, knowledge text, costume id...
    to_character_id: str | None = None  # for PROP_TRANSFER
    note: str = ""


class ProductionElements(BaseModel):
    """Everything the art/sound departments need for a scene."""

    set_dressing: list[str] = Field(default_factory=list)
    food: list[str] = Field(default_factory=list)
    vehicles: list[str] = Field(default_factory=list)
    animals: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)
    rituals: list[str] = Field(default_factory=list)
    gestures: list[str] = Field(default_factory=list)
    sound_music: list[str] = Field(default_factory=list)


class CharacterState(BaseModel):
    """Derived (never hand-edited): a character's state at the END of a scene."""

    costume_id: str = ""
    carrying: list[str] = Field(default_factory=list)  # PROP_* ids
    injuries: list[str] = Field(default_factory=list)  # active, unhealed
    knows: list[str] = Field(default_factory=list)  # knowledge gained so far


class ContinuityWarning(BaseModel):
    id: str = ""  # stable across re-checks (code|entity|scenes), so acknowledgements survive
    code: str  # e.g. PROP_HOLDER_MISMATCH
    severity: Severity = Severity.WARNING
    message: str
    entity_id: str | None = None
    affected_scene_ids: list[str] = Field(default_factory=list)
    acknowledged: bool = False  # user accepts it as intentional
    ack_note: str = ""  # why the user accepted it


class Scene(BaseModel):
    scene_id: str  # SC01
    number: int
    int_ext: IntExt = IntExt.INT
    location_id: str = ""
    sub_location: str = ""
    time: str = ""  # "early morning"
    day: str = ""
    weather: str = ""
    mood: str = ""
    summary: str = ""
    dramatic_purpose: str = ""
    source_text: str = ""  # verbatim scene text: the traceability anchor

    characters: list[str] = Field(default_factory=list)  # CHAR_* ids present
    entrances: list[str] = Field(default_factory=list)
    exits: list[str] = Field(default_factory=list)
    costumes: dict[str, str] = Field(default_factory=dict)  # char id -> costume id
    props_in: list[str] = Field(default_factory=list)  # props present at scene start
    props_out: list[str] = Field(default_factory=list)  # props carried out at the end
    # who holds each prop at the start/end of the scene: CHAR_* id, or "@place" if a location
    prop_holder_start: dict[str, str] = Field(default_factory=dict)
    prop_holder_end: dict[str, str] = Field(default_factory=dict)
    state_changes: list[StateChange] = Field(default_factory=list)
    production: ProductionElements = Field(default_factory=ProductionElements)
    emotional_change: str = ""
    continuity_warnings: list[str] = Field(default_factory=list)  # warning ids affecting this scene
    states: dict[str, CharacterState] = Field(default_factory=dict)  # char id -> state after the scene

    @property
    def costume_ids(self) -> list[str]:
        return list(self.costumes.values())
