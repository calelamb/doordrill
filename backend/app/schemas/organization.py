from pydantic import BaseModel, Field


class OrganizationProfileResponse(BaseModel):
    id: str
    name: str
    industry: str
    plan_tier: str

    model_config = {"from_attributes": True}


class OrganizationUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    industry: str = Field(min_length=1, max_length=120)
