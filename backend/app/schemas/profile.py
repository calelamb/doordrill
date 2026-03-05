from pydantic import BaseModel

class ProfileUpdateRequest(BaseModel):
    name: str | None = None

class HierarchyNode(BaseModel):
    id: str
    name: str
    role: str
    avatar_url: str | None = None
