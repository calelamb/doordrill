from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.ai_meta import AiMeta


class OrgDocumentResponse(BaseModel):
    id: str
    name: str
    original_filename: str
    file_type: str
    status: str
    chunk_count: int | None = None
    token_count: int | None = None
    error_message: str | None = None
    universal_layer_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgDocumentListResponse(BaseModel):
    documents: list[OrgDocumentResponse] = Field(default_factory=list)


class DocumentDeleteResponse(BaseModel):
    ok: bool = True
    document_id: str


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    similarity_score: float
    is_universal: bool = False


class DocumentQueryRequest(BaseModel):
    manager_id: str
    query: str = Field(min_length=1, max_length=4000)
    k: int = Field(default=5, ge=1, le=20)


class DocumentQueryResponse(BaseModel):
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    has_documents: bool


class DocumentAskRequest(BaseModel):
    manager_id: str
    question: str = Field(min_length=1, max_length=4000)


class DocumentAskResponse(BaseModel):
    answer: str
    sources: list[RetrievedChunk] = Field(default_factory=list)
    chunks_used: int = 0
    ai_meta: AiMeta | None = None
