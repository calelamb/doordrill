from typing import Any

from pydantic import BaseModel, Field


class ScenarioCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    industry: str = Field(default="pest_control", max_length=120)
    difficulty: int = Field(default=1, ge=1, le=5)
    description: str = Field(min_length=1, max_length=2000)
    persona: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    stages: list[str] = Field(default_factory=list)
    created_by_id: str


class ScenarioUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    persona: dict[str, Any] | None = None
    rubric: dict[str, Any] | None = None
    stages: list[str] | None = None


class ScenarioResponse(BaseModel):
    id: str
    org_id: str | None
    name: str
    industry: str
    difficulty: int
    description: str
    persona: dict[str, Any]
    rubric: dict[str, Any]
    stages: list[str]
    created_by_id: str | None

    model_config = {"from_attributes": True}


class ObjectionTypeResponse(BaseModel):
    id: str
    org_id: str | None
    tag: str
    display_name: str
    category: str
    difficulty_weight: float
    industry: str | None
    typical_phrases: list[str]
    resolution_techniques: list[str]
    version: str
    active: bool

    model_config = {"from_attributes": True}
