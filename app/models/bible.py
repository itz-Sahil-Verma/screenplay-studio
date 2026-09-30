"""Canonical records: the 'bibles'. One record per real-world thing, reused by ID."""
from pydantic import BaseModel, Field


class Relationship(BaseModel):
    other_id: str  # CHAR_* id of the other character
    relation: str  # e.g. "elder brother", "mother"


class Character(BaseModel):
    id: str  # CHAR_AMAR
    name: str
    aliases: list[str] = Field(default_factory=list)  # "elder son", "A. Singh"
    age: int | None = None
    role: str = ""
    relationships: list[Relationship] = Field(default_factory=list)
    relationship_notes: list[str] = Field(default_factory=list)  # free text from the source
    personality: str = ""
    dialect: str = ""
    emotional_state: str = ""
    physical_description: str = ""  # body, face, apparent age: locked once approved
    # filled from the approved plan (Step 9); the source-side fields above stay as extracted
    adapted_name: str = ""
    adapted_name_native: str = ""
    role_adapted: str = ""
    speech_register: str = ""
    address_terms: list[str] = Field(default_factory=list)
    grooming: str = ""
    scene_ids: list[str] = Field(default_factory=list)  # scenes it appears in
    approved: bool = False


class Location(BaseModel):
    id: str  # LOC_HOME_COURTYARD
    name: str
    adapted_name: str = ""
    adapted_name_native: str = ""
    sub_locations: list[str] = Field(default_factory=list)
    description: str = ""  # architecture, interiors, landscape
    scene_ids: list[str] = Field(default_factory=list)


class Prop(BaseModel):
    id: str  # PROP_LETTER
    name: str
    adapted_name: str = ""
    adapted_name_native: str = ""
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    scene_ids: list[str] = Field(default_factory=list)


class Costume(BaseModel):
    id: str  # COST_AMAR_01
    character_id: str
    source_garments: str | None = None  # what the source said (None = not captured yet); `garments` becomes the adapted one
    garments: str = ""
    fabrics: str = ""
    colours: str = ""
    footwear: str = ""
    jewellery: str = ""
    headwear: str = ""
    grooming: str = ""
    scene_ids: list[str] = Field(default_factory=list)  # where it is worn
    change_reason: str = ""  # required story reason if this replaces an earlier costume
    approved: bool = False
