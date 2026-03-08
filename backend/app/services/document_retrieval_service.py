from __future__ import annotations

import math
from sqlalchemy import text as sql_text
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentStatus
from app.schemas.knowledge import RetrievedChunk
from app.services.document_processing_service import EMBEDDING_MODEL, DocumentProcessingService
from app.services.management_cache_service import ManagementCacheService


class DocumentRetrievalService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        processing_service: DocumentProcessingService | None = None,
        cache_service: ManagementCacheService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.processing_service = processing_service or DocumentProcessingService(settings=self.settings)
        self.cache = cache_service or ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=900,
            max_entries=self.settings.management_analytics_cache_max_entries,
        )

    def has_ready_documents(self, db: Session, *, org_id: str) -> bool:
        row = db.scalar(
            select(OrgDocument.id)
            .where(
                OrgDocument.org_id == org_id,
                OrgDocument.status == OrgDocumentStatus.READY,
            )
            .limit(1)
        )
        return row is not None

    def retrieve(
        self,
        db: Session,
        *,
        org_id: str,
        query: str,
        k: int = 5,
        min_score: float = 0.70,
    ) -> list[RetrievedChunk]:
        normalized_query = " ".join(query.split()).strip()
        if not normalized_query:
            return []
        if not self.has_ready_documents(db, org_id=org_id):
            return []

        query_vector = self._embed_query(normalized_query)
        dialect_name = db.bind.dialect.name if db.bind is not None else ""
        if dialect_name == "postgresql":
            rows = self._retrieve_postgres(db, org_id=org_id, query_vector=query_vector, k=k)
        else:
            rows = self._retrieve_python(db, org_id=org_id, query_vector=query_vector, k=k)

        return [row for row in rows if row.similarity_score >= min_score]

    def retrieve_for_topic(
        self,
        db: Session,
        *,
        org_id: str,
        topic: str,
        context_hint: str = "",
        k: int = 5,
        min_score: float = 0.70,
    ) -> list[RetrievedChunk]:
        prompt = f"Topic: {topic.strip()}"
        if context_hint.strip():
            prompt = f"{prompt}\nContext: {context_hint.strip()}"
        return self.retrieve(db, org_id=org_id, query=prompt, k=k, min_score=min_score)

    def format_for_prompt(self, chunks: list[RetrievedChunk], max_tokens: int = 1200) -> str:
        if not chunks:
            return ""

        header = "=== Company Training Material ==="
        footer = "=== End Company Training Material ==="
        consumed_tokens = self.processing_service.count_tokens(header) + self.processing_service.count_tokens(footer)
        entries: list[str] = []

        for chunk in chunks:
            prefix = f"[From: {chunk.document_name}]"
            prefix_tokens = self.processing_service.count_tokens(prefix)
            remaining = max_tokens - consumed_tokens - prefix_tokens
            if remaining <= 0:
                break

            chunk_text = chunk.text.strip()
            chunk_tokens = self.processing_service.count_tokens(chunk_text)
            if chunk_tokens > remaining:
                chunk_text = self._truncate_text_to_token_budget(chunk_text, remaining)
                if not chunk_text:
                    break
                entries.append(f"{prefix}\n{chunk_text}")
                break

            entries.append(f"{prefix}\n{chunk_text}")
            consumed_tokens += prefix_tokens + chunk_tokens

        if not entries:
            return ""
        return f"{header}\n" + "\n\n".join(entries) + f"\n{footer}"

    def _embed_query(self, query: str) -> list[float]:
        cache_key = self.cache.make_key(
            "knowledge-query-embedding",
            {"model": EMBEDDING_MODEL, "query": query},
        )
        cached = self.cache.get_json(cache_key)
        if cached and isinstance(cached.get("embedding"), list):
            return [float(value) for value in cached["embedding"]]

        embedding = self.processing_service.embed_chunks([query])[0]
        self.cache.set_json(cache_key, {"embedding": embedding})
        return embedding

    def _retrieve_postgres(
        self,
        db: Session,
        *,
        org_id: str,
        query_vector: list[float],
        k: int,
    ) -> list[RetrievedChunk]:
        query_vector_literal = "[" + ",".join(f"{value:.12f}" for value in query_vector) + "]"
        rows = db.execute(
            sql_text(
                """
                SELECT
                    chunk.id AS chunk_id,
                    chunk.text AS text,
                    chunk.document_id AS document_id,
                    doc.name AS document_name,
                    1 - (chunk.embedding <=> CAST(:query_vector AS vector)) AS similarity
                FROM org_document_chunks chunk
                JOIN org_documents doc ON doc.id = chunk.document_id
                WHERE chunk.org_id = :org_id
                  AND doc.status = :ready_status
                  AND chunk.embedding IS NOT NULL
                ORDER BY chunk.embedding <=> CAST(:query_vector AS vector)
                LIMIT :k
                """
            ),
            {
                "org_id": org_id,
                "query_vector": query_vector_literal,
                "ready_status": OrgDocumentStatus.READY.value,
                "k": k,
            },
        ).mappings().all()
        return [
            RetrievedChunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_name=row["document_name"],
                text=row["text"],
                similarity_score=float(row["similarity"] or 0.0),
            )
            for row in rows
        ]

    def _retrieve_python(
        self,
        db: Session,
        *,
        org_id: str,
        query_vector: list[float],
        k: int,
    ) -> list[RetrievedChunk]:
        rows = db.execute(
            select(OrgDocumentChunk, OrgDocument.name)
            .join(OrgDocument, OrgDocument.id == OrgDocumentChunk.document_id)
            .where(
                OrgDocumentChunk.org_id == org_id,
                OrgDocument.status == OrgDocumentStatus.READY,
                OrgDocumentChunk.embedding.is_not(None),
            )
        ).all()

        scored: list[RetrievedChunk] = []
        for chunk, document_name in rows:
            similarity = self._cosine_similarity(query_vector, chunk.embedding or [])
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_name=document_name,
                    text=chunk.text,
                    similarity_score=similarity,
                )
            )

        scored.sort(key=lambda item: item.similarity_score, reverse=True)
        return scored[:k]

    def _truncate_text_to_token_budget(self, text: str, token_budget: int) -> str:
        words = text.split()
        if not words or token_budget <= 0:
            return ""

        best = ""
        low = 1
        high = len(words)
        while low <= high:
            mid = (low + high) // 2
            candidate = " ".join(words[:mid]).strip()
            if self.processing_service.count_tokens(candidate) <= token_budget:
                best = candidate
                low = mid + 1
            else:
                high = mid - 1
        return best

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)
