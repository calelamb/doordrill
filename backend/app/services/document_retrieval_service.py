from __future__ import annotations

import asyncio
import inspect
import math
import os
import re
import threading

from cachetools import TTLCache
import httpx
from sqlalchemy import or_, select
from sqlalchemy import text as sql_text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.org_material import OrgKnowledgeDoc, OrgMaterial
from app.models.types import OrgDocumentStatus
from app.models.universal_knowledge import UniversalKnowledgeChunk
from app.schemas.knowledge import RetrievedChunk
from app.services.document_processing_service import DocumentProcessingService
from app.services.management_cache_service import ManagementCacheService
from app.services.universal_knowledge_service import UNIVERSAL_CATEGORIES

KEYWORD_RE = re.compile(r"[a-z0-9]{3,}")
UNIVERSAL_CATEGORY_RE = re.compile(r"\[([a-z_]+)\]")
CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "intro": (
        "door approach",
        "social proof",
        "neighbor on the route",
        "first contact",
        "front step",
    ),
    "objection_handling": (
        "not interested",
        "already have a guy",
        "think about it",
        "we just moved in",
        "do it ourselves",
        "diy",
    ),
    "reading_homeowner": (
        "engagement signals",
        "disengagement signals",
        "body language",
        "eye contact",
        "skepticism signals",
    ),
    "price_framing": (
        "bimonthly",
        "quarterly",
        "monthly is",
        "price anchor",
        "startup fee",
    ),
    "closing": (
        "assumptive close",
        "option close",
        "assignment close",
        "tuesday or thursday",
        "level up moment",
    ),
    "psychology": (
        "reactance",
        "loss aversion",
        "decision fatigue",
        "first-impression bias",
        "prior bad experience",
    ),
    "service_value": (
        "feature-benefit",
        "dewebbing",
        "perimeter",
        "pet and kid safe",
        "no annual contract",
    ),
    "competitor_handling": (
        "switch over",
        "terminix",
        "orkin",
        "aptive",
        "competitor",
    ),
    "post_pitch": (
        "post-pitch",
        "outside-the-sale",
        "call you later",
        "swing back in 15 minutes",
    ),
    "backyard_close": (
        "backyard close",
        "backyard",
        "standing water",
        "grub damage",
    ),
}


class DocumentRetrievalService:
    TOPIC_RESULT_CACHE_TTL_SECONDS = 300
    TOPIC_RESULT_CACHE_MAX_ENTRIES = 256

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
        self._topic_result_cache: TTLCache[tuple[str, str, int, str], list[RetrievedChunk]] = TTLCache(
            maxsize=self.TOPIC_RESULT_CACHE_MAX_ENTRIES,
            ttl=self.TOPIC_RESULT_CACHE_TTL_SECONDS,
        )
        self._topic_result_cache_lock = threading.RLock()

    def has_ready_documents(self, db: Session, *, org_id: str) -> bool:
        material_row = db.scalar(
            select(OrgKnowledgeDoc.id)
            .join(OrgMaterial, OrgMaterial.id == OrgKnowledgeDoc.material_id)
            .where(
                OrgKnowledgeDoc.org_id == org_id,
                OrgKnowledgeDoc.embedding.is_not(None),
                OrgMaterial.deleted_at.is_(None),
            )
            .limit(1)
        )
        if material_row is not None:
            return True

        row = db.scalar(
            select(OrgDocument.id)
            .where(
                OrgDocument.org_id == org_id,
                OrgDocument.status == OrgDocumentStatus.READY,
            )
            .limit(1)
        )
        if row is not None:
            return True

        universal_row = db.scalar(
            select(UniversalKnowledgeChunk.id)
            .where(UniversalKnowledgeChunk.is_active.is_(True))
            .limit(1)
        )
        return universal_row is not None

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

        material_rows: list[RetrievedChunk] = []
        try:
            query_vector = self._resolve_query_embedding(normalized_query)
            material_rows = self._retrieve_material_docs_python(
                db,
                org_id=org_id,
                query_vector=query_vector,
                k=k,
                include_raw_chunks=True,
            )
        except Exception:
            material_rows = self._retrieve_material_docs_keyword(
                db,
                org_id=org_id,
                query_text=normalized_query,
                k=k,
                include_raw_chunks=True,
            )
            legacy_rows = self._retrieve_keyword(db, org_id=org_id, query_text=normalized_query, k=k)
            org_rows = [row for row in self._merge_results(material_rows, legacy_rows, k=k) if row.similarity_score >= min_score]
            universal_rows = self._retrieve_universal_keyword(db, query_text=normalized_query, k=k)
            return self._merge_with_universal(
                org_rows=org_rows,
                universal_rows=universal_rows,
                k=k,
                min_score=min_score,
            )

        dialect_name = db.bind.dialect.name if db.bind is not None else ""
        if dialect_name == "postgresql" and self._supports_postgres_vector_search(db):
            try:
                legacy_rows = self._retrieve_postgres(db, org_id=org_id, query_vector=query_vector, k=k)
            except DBAPIError:
                legacy_rows = self._retrieve_python(db, org_id=org_id, query_vector=query_vector, k=k)
        else:
            legacy_rows = self._retrieve_python(db, org_id=org_id, query_vector=query_vector, k=k)

        org_rows = [row for row in self._merge_results(material_rows, legacy_rows, k=k) if row.similarity_score >= min_score]
        universal_rows = self._retrieve_universal_python(db, query_vector=query_vector, k=k)
        if not universal_rows:
            universal_rows = self._retrieve_universal_keyword(db, query_text=normalized_query, k=k)
        return self._merge_with_universal(
            org_rows=org_rows,
            universal_rows=universal_rows,
            k=k,
            min_score=min_score,
        )

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
        normalized_prompt = " ".join(prompt.split()).strip()
        if not normalized_prompt:
            return []
        if not self.has_ready_documents(db, org_id=org_id):
            return []

        cache_key = (str(org_id or "__global__"), " ".join(topic.split()).strip().lower(), int(k), f"{min_score:.2f}")
        cached_rows = self._get_cached_topic_results(cache_key)
        if cached_rows is not None:
            return cached_rows

        org_rows: list[RetrievedChunk]
        query_vector: list[float] | None = None
        try:
            query_vector = self._resolve_query_embedding(normalized_prompt)
        except Exception:
            query_vector = None

        structured_rows: list[RetrievedChunk]
        if query_vector is not None:
            structured_rows = self._retrieve_material_docs_python(
                db,
                org_id=org_id,
                query_vector=query_vector,
                k=k,
                include_raw_chunks=False,
            )
        else:
            structured_rows = self._retrieve_material_docs_keyword(
                db,
                org_id=org_id,
                query_text=normalized_prompt,
                k=k,
                include_raw_chunks=False,
            )

        if structured_rows:
            org_rows = [row for row in structured_rows if row.similarity_score >= min_score]
        elif query_vector is not None:
            raw_chunk_rows = self._retrieve_material_docs_python(
                db,
                org_id=org_id,
                query_vector=query_vector,
                k=k,
                include_raw_chunks=True,
            )
            dialect_name = db.bind.dialect.name if db.bind is not None else ""
            if dialect_name == "postgresql" and self._supports_postgres_vector_search(db):
                try:
                    legacy_rows = self._retrieve_postgres(db, org_id=org_id, query_vector=query_vector, k=k)
                except DBAPIError:
                    legacy_rows = self._retrieve_keyword(db, org_id=org_id, query_text=normalized_prompt, k=k)
            else:
                legacy_rows = self._retrieve_keyword(db, org_id=org_id, query_text=normalized_prompt, k=k)
            org_rows = [
                row for row in self._merge_results(raw_chunk_rows, legacy_rows, k=k) if row.similarity_score >= min_score
            ]
        else:
            raw_chunk_rows = self._retrieve_material_docs_keyword(
                db,
                org_id=org_id,
                query_text=normalized_prompt,
                k=k,
                include_raw_chunks=True,
            )
            legacy_rows = self._retrieve_keyword(db, org_id=org_id, query_text=normalized_prompt, k=k)
            org_rows = [
                row for row in self._merge_results(raw_chunk_rows, legacy_rows, k=k) if row.similarity_score >= min_score
            ]

        if query_vector is not None:
            universal_rows = self._retrieve_universal_python(db, query_vector=query_vector, k=k)
            if not universal_rows:
                universal_rows = self._retrieve_universal_keyword(db, query_text=normalized_prompt, k=k)
        else:
            universal_rows = self._retrieve_universal_keyword(db, query_text=normalized_prompt, k=k)

        rows = self._merge_with_universal(
            org_rows=org_rows,
            universal_rows=universal_rows,
            k=k,
            min_score=min_score,
        )
        self._set_cached_topic_results(cache_key, rows)
        return rows

    def _get_cached_topic_results(self, cache_key: tuple[str, str, int, str]) -> list[RetrievedChunk] | None:
        with self._topic_result_cache_lock:
            cached_rows = self._topic_result_cache.get(cache_key)
            if cached_rows is None:
                return None
            return [row.model_copy(deep=True) for row in cached_rows]

    def _set_cached_topic_results(self, cache_key: tuple[str, str, int, str], rows: list[RetrievedChunk]) -> None:
        with self._topic_result_cache_lock:
            self._topic_result_cache[cache_key] = [row.model_copy(deep=True) for row in rows]

    def format_for_prompt(self, chunks: list[RetrievedChunk], max_tokens: int = 1200) -> str:
        if not chunks:
            return ""

        org_chunks = [chunk for chunk in chunks if not chunk.is_universal]
        universal_chunks = [chunk for chunk in chunks if chunk.is_universal]

        parts: list[str] = []
        remaining_budget = max_tokens

        if org_chunks:
            org_block, consumed = self._format_chunk_block(
                org_chunks,
                header="=== Company Training Material ===",
                footer="=== End Company Training Material ===",
                token_budget=remaining_budget,
            )
            if org_block:
                parts.append(org_block)
                remaining_budget -= consumed

        if universal_chunks and remaining_budget > 100:
            universal_block, _ = self._format_chunk_block(
                universal_chunks,
                header="=== Industry Sales Knowledge ===",
                footer="=== End Industry Sales Knowledge ===",
                token_budget=remaining_budget,
            )
            if universal_block:
                parts.append(universal_block)

        return "\n\n".join(parts)

    async def _embed_query(self, query: str) -> list[float]:
        cache_key = self.cache.make_key(
            "knowledge-query-embedding",
            {"model": self.settings.embedding_model, "query": query},
        )
        cached = self.cache.get_json(cache_key)
        if cached and isinstance(cached.get("embedding"), list):
            return [float(value) for value in cached["embedding"]]

        if not self.settings.openai_api_key or os.getenv("PYTEST_CURRENT_TEST"):
            embedding = self.processing_service.embed_chunks([query])[0]
            self.cache.set_json(cache_key, {"embedding": embedding})
            return embedding

        url = f"{self.settings.openai_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.post(
                url,
                headers=headers,
                json={"model": self.settings.embedding_model, "input": query},
            )
            response.raise_for_status()
            body = response.json()
        data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        if not data:
            raise ValueError("embedding response was empty")
        embedding = [float(value) for value in data[0]["embedding"]]
        self.cache.set_json(cache_key, {"embedding": embedding})
        return embedding

    def _resolve_query_embedding(self, query: str) -> list[float]:
        result = self._embed_query(query)
        if inspect.isawaitable(result):
            resolved = self._run_async(result)
        else:
            resolved = result
        return [float(value) for value in resolved]

    def _run_async(self, coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result: dict[str, object] = {}
        error: dict[str, BaseException] = {}

        def runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result["value"] = loop.run_until_complete(coro)
            except BaseException as exc:  # pragma: no cover - defensive thread bridge
                error["exc"] = exc
            finally:
                asyncio.set_event_loop(None)
                loop.close()

        import threading

        thread = threading.Thread(target=runner)
        thread.start()
        thread.join()
        if "exc" in error:
            raise error["exc"]
        return result["value"]

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

    def _supports_postgres_vector_search(self, db: Session) -> bool:
        bind = db.bind
        if bind is None or bind.dialect.name != "postgresql":
            return False

        embedding_type = OrgDocumentChunk.__table__.c.embedding.type.load_dialect_impl(bind.dialect)
        if embedding_type.__class__.__name__.lower() != "vector":
            return False

        try:
            return bool(db.scalar(sql_text("SELECT to_regtype('vector') IS NOT NULL")))
        except DBAPIError:
            return False

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

    def _retrieve_material_docs_python(
        self,
        db: Session,
        *,
        org_id: str | None,
        query_vector: list[float],
        k: int,
        include_raw_chunks: bool,
    ) -> list[RetrievedChunk]:
        stmt = (
            select(OrgKnowledgeDoc, OrgMaterial.original_filename)
            .join(OrgMaterial, OrgMaterial.id == OrgKnowledgeDoc.material_id)
            .where(
                OrgMaterial.deleted_at.is_(None),
                OrgKnowledgeDoc.embedding.is_not(None),
            )
        )
        if org_id is None:
            stmt = stmt.where(OrgKnowledgeDoc.org_id.is_(None))
        else:
            stmt = stmt.where(OrgKnowledgeDoc.org_id == org_id)
        if include_raw_chunks:
            stmt = stmt.where(OrgKnowledgeDoc.extraction_type == "raw_chunk")
        else:
            stmt = stmt.where(OrgKnowledgeDoc.extraction_type != "raw_chunk")
            stmt = stmt.where(OrgKnowledgeDoc.manager_approved.is_not(False))

        rows = db.execute(stmt).all()
        scored: list[RetrievedChunk] = []
        for doc, document_name in rows:
            similarity = self._cosine_similarity(query_vector, doc.embedding or [])
            scored.append(
                RetrievedChunk(
                    chunk_id=str(doc.id),
                    document_id=str(doc.material_id),
                    document_name=document_name,
                    text=doc.content,
                    similarity_score=similarity,
                )
            )
        scored.sort(key=lambda item: item.similarity_score, reverse=True)
        return scored[:k]

    def _retrieve_material_docs_keyword(
        self,
        db: Session,
        *,
        org_id: str | None,
        query_text: str,
        k: int,
        include_raw_chunks: bool,
    ) -> list[RetrievedChunk]:
        terms = self._keyword_terms(query_text)
        if not terms:
            return []

        stmt = (
            select(OrgKnowledgeDoc, OrgMaterial.original_filename)
            .join(OrgMaterial, OrgMaterial.id == OrgKnowledgeDoc.material_id)
            .where(OrgMaterial.deleted_at.is_(None))
        )
        if org_id is None:
            stmt = stmt.where(OrgKnowledgeDoc.org_id.is_(None))
        else:
            stmt = stmt.where(OrgKnowledgeDoc.org_id == org_id)
        if include_raw_chunks:
            stmt = stmt.where(OrgKnowledgeDoc.extraction_type == "raw_chunk")
        else:
            stmt = stmt.where(OrgKnowledgeDoc.extraction_type != "raw_chunk")
            stmt = stmt.where(OrgKnowledgeDoc.manager_approved.is_not(False))

        rows = db.execute(stmt).all()
        scored: list[RetrievedChunk] = []
        for doc, document_name in rows:
            similarity = self._keyword_similarity(doc.content, terms)
            if similarity <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    chunk_id=str(doc.id),
                    document_id=str(doc.material_id),
                    document_name=document_name,
                    text=doc.content,
                    similarity_score=similarity,
                )
            )
        scored.sort(key=lambda item: (item.similarity_score, len(item.text)), reverse=True)
        return scored[:k]

    def _retrieve_keyword(
        self,
        db: Session,
        *,
        org_id: str,
        query_text: str,
        k: int,
    ) -> list[RetrievedChunk]:
        terms = self._keyword_terms(query_text)
        if not terms:
            return []

        rows = db.execute(
            select(OrgDocumentChunk, OrgDocument.name)
            .join(OrgDocument, OrgDocument.id == OrgDocumentChunk.document_id)
            .where(
                OrgDocumentChunk.org_id == org_id,
                OrgDocument.status == OrgDocumentStatus.READY,
                or_(*[OrgDocumentChunk.text.ilike(f"%{term}%") for term in terms]),
            )
        ).all()

        scored: list[RetrievedChunk] = []
        for chunk, document_name in rows:
            text_lower = (chunk.text or "").lower()
            matched = sum(1 for term in terms if term in text_lower)
            if matched <= 0:
                continue
            similarity = max(0.7, matched / max(1, len(terms)))
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_name=document_name,
                    text=chunk.text,
                    similarity_score=round(min(1.0, similarity), 4),
                )
            )

        scored.sort(key=lambda item: (item.similarity_score, len(item.text)), reverse=True)
        return scored[:k]

    def _retrieve_universal_python(
        self,
        db: Session,
        *,
        query_vector: list[float],
        k: int,
    ) -> list[RetrievedChunk]:
        rows = db.execute(
            select(UniversalKnowledgeChunk)
            .where(UniversalKnowledgeChunk.is_active.is_(True))
            .where(UniversalKnowledgeChunk.embedding.is_not(None))
        ).scalars().all()

        scored: list[RetrievedChunk] = []
        for chunk in rows:
            similarity = self._cosine_similarity(query_vector, chunk.embedding or [])
            scored.append(
                RetrievedChunk(
                    chunk_id=str(chunk.id),
                    document_id="universal",
                    document_name=f"Industry Knowledge [{chunk.category}]",
                    text=chunk.content,
                    similarity_score=similarity,
                    is_universal=True,
                )
            )

        scored.sort(key=lambda item: item.similarity_score, reverse=True)
        return scored[:k]

    def _retrieve_universal_keyword(
        self,
        db: Session,
        *,
        query_text: str,
        k: int,
    ) -> list[RetrievedChunk]:
        terms = self._keyword_terms(query_text)
        if not terms:
            return []

        rows = db.execute(
            select(UniversalKnowledgeChunk)
            .where(UniversalKnowledgeChunk.is_active.is_(True))
        ).scalars().all()

        scored: list[RetrievedChunk] = []
        for chunk in rows:
            similarity = self._keyword_similarity(chunk.content, terms)
            if similarity <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    chunk_id=str(chunk.id),
                    document_id="universal",
                    document_name=f"Industry Knowledge [{chunk.category}]",
                    text=chunk.content,
                    similarity_score=similarity,
                    is_universal=True,
                )
            )

        scored.sort(key=lambda item: (item.similarity_score, len(item.text)), reverse=True)
        return scored[:k]

    def _keyword_terms(self, query_text: str) -> list[str]:
        terms = KEYWORD_RE.findall(query_text.lower())
        unique_terms: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            unique_terms.append(term)
        return unique_terms[:12]

    def _keyword_similarity(self, text: str, terms: list[str]) -> float:
        text_lower = (text or "").lower()
        matched = sum(1 for term in terms if term in text_lower)
        if matched <= 0:
            return 0.0
        similarity = max(0.7, matched / max(1, len(terms)))
        return round(min(1.0, similarity), 4)

    def _merge_results(
        self,
        primary: list[RetrievedChunk],
        secondary: list[RetrievedChunk],
        *,
        k: int,
    ) -> list[RetrievedChunk]:
        seen: set[tuple[str, str]] = set()
        merged: list[RetrievedChunk] = []
        for row in [*primary, *secondary]:
            key = (row.document_id, row.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
        merged.sort(key=lambda item: item.similarity_score, reverse=True)
        return merged[:k]

    def _merge_with_universal(
        self,
        *,
        org_rows: list[RetrievedChunk],
        universal_rows: list[RetrievedChunk],
        k: int,
        min_score: float = 0.70,
    ) -> list[RetrievedChunk]:
        result = list(org_rows[:k])
        occupied_categories = self._covered_categories(result)
        seen: set[tuple[str, str]] = {(row.document_id, row.chunk_id) for row in result}

        for universal in universal_rows:
            if len(result) >= k:
                break
            if universal.similarity_score < min_score:
                continue
            key = (universal.document_id, universal.chunk_id)
            if key in seen:
                continue
            category = self._extract_universal_category(universal)
            if category is not None and category in occupied_categories:
                continue
            seen.add(key)
            if category is not None:
                occupied_categories.add(category)
            result.append(universal)

        return result

    def _covered_categories(self, rows: list[RetrievedChunk]) -> set[str]:
        covered: set[str] = set()
        for row in rows:
            category = self._infer_chunk_category(row)
            if category in UNIVERSAL_CATEGORIES:
                covered.add(category)
        return covered

    def _infer_chunk_category(self, row: RetrievedChunk) -> str | None:
        universal_category = self._extract_universal_category(row)
        if universal_category is not None:
            return universal_category

        haystack = f"{row.document_name}\n{row.text}".lower()
        best_category: str | None = None
        best_score = 0
        for category, hints in CATEGORY_HINTS.items():
            score = sum(1 for hint in hints if hint in haystack)
            if score > best_score:
                best_category = category
                best_score = score
        return best_category if best_score > 0 else None

    def _extract_universal_category(self, row: RetrievedChunk) -> str | None:
        if not row.is_universal and "Industry Knowledge [" not in row.document_name:
            return None
        match = UNIVERSAL_CATEGORY_RE.search(row.document_name)
        if match is None:
            return None
        category = match.group(1).strip()
        if category not in UNIVERSAL_CATEGORIES:
            return None
        return category

    def _format_chunk_block(
        self,
        chunks: list[RetrievedChunk],
        *,
        header: str,
        footer: str,
        token_budget: int,
    ) -> tuple[str, int]:
        consumed_tokens = self.processing_service.count_tokens(header) + self.processing_service.count_tokens(footer)
        entries: list[str] = []

        for chunk in chunks:
            prefix = f"[From: {chunk.document_name}]"
            prefix_tokens = self.processing_service.count_tokens(prefix)
            remaining = token_budget - consumed_tokens - prefix_tokens
            if remaining <= 0:
                break

            chunk_text = chunk.text.strip()
            chunk_tokens = self.processing_service.count_tokens(chunk_text)
            if chunk_tokens > remaining:
                chunk_text = self._truncate_text_to_token_budget(chunk_text, remaining)
                if not chunk_text:
                    break
                chunk_tokens = self.processing_service.count_tokens(chunk_text)
                entries.append(f"{prefix}\n{chunk_text}")
                consumed_tokens += prefix_tokens + chunk_tokens
                break

            entries.append(f"{prefix}\n{chunk_text}")
            consumed_tokens += prefix_tokens + chunk_tokens

        if not entries:
            return "", 0
        return f"{header}\n" + "\n\n".join(entries) + f"\n{footer}", consumed_tokens

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
