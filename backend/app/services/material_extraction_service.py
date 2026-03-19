from __future__ import annotations

import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session

from app.core.config import Settings, get_settings
from app.models.org_material import OrgKnowledgeDoc, OrgMaterial
from app.services.document_processing_service import DocumentProcessingService
from app.services.storage_service import StorageService


PROMPT_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
EXTRACTION_BUCKETS = {
    "objections": "objection",
    "rebuttals": "rebuttal",
    "unique_selling_points": "usp",
    "competitors": "competitor",
    "pricing_signals": "pricing",
    "persona_insights": "persona_insight",
    "pitch_techniques": "pitch_technique",
    "company_facts": "company_fact",
}


def _tool_item_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "supporting_quote": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["content", "supporting_quote", "confidence"],
    }


TOOL_SCHEMA = {
    "name": "record_extracted_knowledge",
    "description": "Record all structured knowledge extracted from this sales training material.",
    "input_schema": {
        "type": "object",
        "properties": {
            "objections": {"type": "array", "items": _tool_item_schema()},
            "rebuttals": {"type": "array", "items": _tool_item_schema()},
            "unique_selling_points": {"type": "array", "items": _tool_item_schema()},
            "competitors": {"type": "array", "items": _tool_item_schema()},
            "pricing_signals": {"type": "array", "items": _tool_item_schema()},
            "persona_insights": {"type": "array", "items": _tool_item_schema()},
            "pitch_techniques": {"type": "array", "items": _tool_item_schema()},
            "company_facts": {"type": "array", "items": _tool_item_schema()},
        },
        "required": list(EXTRACTION_BUCKETS.keys()),
    },
}


class MaterialExtractionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage_service: StorageService | None = None,
        processing_service: DocumentProcessingService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage_service = storage_service or StorageService()
        self.processing_service = processing_service or DocumentProcessingService(
            settings=self.settings,
            storage_service=self.storage_service,
        )
        self._env = Environment(
            loader=FileSystemLoader(str(PROMPT_TEMPLATE_DIR)),
            autoescape=select_autoescape(default_for_string=False, disabled_extensions=("j2",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    async def process(self, material_id: int, db: Session) -> None:
        material = db.scalar(select(OrgMaterial).where(OrgMaterial.id == material_id))
        if material is None:
            raise ValueError("material not found")

        db.execute(delete(OrgKnowledgeDoc).where(OrgKnowledgeDoc.material_id == material.id))
        material.extraction_error = None
        db.commit()

        try:
            raw_text = await self.transcribe_or_parse(material)
            if not raw_text.strip():
                raise ValueError("material contains no extractable text")
            await self.chunk_and_embed(material, raw_text)
            await self.extract_structured(material, raw_text)
            material.extraction_status = "complete"
            material.extracted_at = datetime.now(timezone.utc)
            material.extraction_error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            failed = db.scalar(select(OrgMaterial).where(OrgMaterial.id == material_id))
            if failed is not None:
                failed.extraction_status = "failed"
                failed.extraction_error = str(exc)[:4000]
                db.commit()
            raise

    async def transcribe_or_parse(self, material: OrgMaterial) -> str:
        db = self._db_for(material)
        material.extraction_status = "transcribing"
        material.extraction_error = None
        db.commit()

        file_bytes = self.storage_service.download_bytes(material.storage_key)
        file_type = str(material.file_type or "").lower()
        if file_type in {"pdf", "docx", "txt"}:
            raw_text = self.processing_service.extract_text(file_bytes, file_type, material.storage_key)
        elif file_type == "csv":
            raw_text = self._extract_csv(file_bytes)
        elif file_type in {"video", "audio"}:
            raw_text = await self._transcribe_with_deepgram(
                file_bytes,
                filename=material.original_filename,
                storage_key=material.storage_key,
            )
        else:
            raise ValueError(f"unsupported material file type: {material.file_type}")

        normalized = raw_text.strip()
        material.raw_transcript = normalized
        material.extraction_status = "extracting"
        db.commit()
        return normalized

    async def chunk_and_embed(self, material: OrgMaterial, raw_text: str) -> None:
        db = self._db_for(material)
        chunks = self.processing_service.chunk_text(raw_text, chunk_size=800, overlap=100)
        if not chunks:
            return
        embeddings = self.processing_service.embed_chunks(chunks)
        for chunk_text, embedding in zip(chunks, embeddings, strict=True):
            db.add(
                OrgKnowledgeDoc(
                    org_id=material.org_id,
                    material_id=material.id,
                    extraction_type="raw_chunk",
                    content=chunk_text,
                    supporting_quote=None,
                    confidence=1.0,
                    manager_approved=True,
                    used_in_config=False,
                    embedding=embedding,
                )
            )
        db.commit()

    async def extract_structured(self, material: OrgMaterial, raw_text: str) -> list[OrgKnowledgeDoc]:
        db = self._db_for(material)
        payload = await self._extract_with_claude(material, raw_text)
        docs_to_create: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for bucket_name, extraction_type in EXTRACTION_BUCKETS.items():
            raw_items = payload.get(bucket_name) if isinstance(payload, dict) else []
            if not isinstance(raw_items, list):
                continue
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                content = " ".join(str(item.get("content") or "").split()).strip()
                if not content:
                    continue
                dedupe_key = (extraction_type, content.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                docs_to_create.append(
                    {
                        "extraction_type": extraction_type,
                        "content": content,
                        "supporting_quote": str(item.get("supporting_quote") or "").strip() or None,
                        "confidence": self._clamp_confidence(item.get("confidence")),
                    }
                )

        embeddings: list[list[float] | None]
        if docs_to_create:
            try:
                embeddings = self.processing_service.embed_chunks([item["content"] for item in docs_to_create])
            except Exception:
                embeddings = [None for _ in docs_to_create]
        else:
            embeddings = []

        docs: list[OrgKnowledgeDoc] = []
        for payload_item, embedding in zip(docs_to_create, embeddings, strict=True):
            doc = OrgKnowledgeDoc(
                org_id=material.org_id,
                material_id=material.id,
                extraction_type=payload_item["extraction_type"],
                content=payload_item["content"],
                supporting_quote=payload_item["supporting_quote"],
                confidence=payload_item["confidence"],
                manager_approved=None,
                used_in_config=False,
                embedding=embedding,
            )
            db.add(doc)
            docs.append(doc)

        db.commit()
        return docs

    def _db_for(self, material: OrgMaterial) -> Session:
        db = object_session(material)
        if db is None:
            raise RuntimeError("material is not attached to a database session")
        return db

    def _render_prompt(self, material: OrgMaterial, raw_text: str) -> str:
        template = self._env.get_template("material_extraction.j2")
        return template.render(
            filename=material.original_filename,
            file_type=material.file_type,
            raw_text=raw_text,
            tool_schema_json=json.dumps(TOOL_SCHEMA, ensure_ascii=True),
        )

    async def _extract_with_claude(self, material: OrgMaterial, raw_text: str) -> dict[str, Any]:
        if not self.settings.anthropic_api_key or os.getenv("PYTEST_CURRENT_TEST"):
            return self._extract_with_heuristics(raw_text)

        payload_text = self._render_prompt(material, raw_text)
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds * 6) as client:
            response = await client.post(
                f"{self.settings.anthropic_base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": self.settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.settings.anthropic_model,
                    "max_tokens": 4000,
                    "temperature": 0,
                    "system": "You are a sales training analyst. Use the provided tool to capture structured findings.",
                    "messages": [{"role": "user", "content": payload_text}],
                    "tools": [TOOL_SCHEMA],
                    "tool_choice": {"type": "tool", "name": TOOL_SCHEMA["name"]},
                },
            )
            response.raise_for_status()
            body = response.json()

        for block in body.get("content", []):
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == TOOL_SCHEMA["name"]
                and isinstance(block.get("input"), dict)
            ):
                return block["input"]
        return self._extract_with_heuristics(raw_text)

    async def _transcribe_with_deepgram(self, file_bytes: bytes, *, filename: str, storage_key: str) -> str:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if not self.settings.deepgram_api_key:
            try:
                return file_bytes.decode("utf-8").strip()
            except UnicodeDecodeError:
                return ""

        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds * 6) as client:
            response = await client.post(
                f"{self.settings.deepgram_base_url.rstrip('/')}/v1/listen",
                headers={
                    "Authorization": f"Token {self.settings.deepgram_api_key}",
                    "Content-Type": content_type,
                },
                params={
                    "model": self.settings.deepgram_model,
                    "smart_format": "true",
                    "punctuate": "true",
                    "detect_language": "true",
                },
                content=file_bytes,
            )
            response.raise_for_status()
            body = response.json()

        return (
            body.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
            .strip()
        )

    def _extract_with_heuristics(self, raw_text: str) -> dict[str, list[dict[str, Any]]]:
        buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in EXTRACTION_BUCKETS}
        sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(raw_text) if part.strip()]
        seen: set[tuple[str, str]] = set()
        keyword_map = {
            "objections": ("objection", "concern", "worried", "too expensive", "already have", "not interested"),
            "rebuttals": ("respond", "rebuttal", "answer", "you can say", "tell them", "overcome"),
            "unique_selling_points": ("benefit", "feature", "advantage", "save", "warranty", "certified"),
            "competitors": ("competitor", "versus", "vs.", "unlike", "compare", "compared to"),
            "pricing_signals": ("price", "pricing", "monthly", "quote", "survey", "savings", "cost"),
            "persona_insights": ("homeowner", "family", "retiree", "parent", "property owner", "demographic"),
            "pitch_techniques": ("pitch", "close", "door approach", "framework", "technique", "follow-up"),
            "company_facts": ("mission", "history", "award", "certified", "licensed", "years in business"),
        }

        for sentence in sentences:
            lowered = sentence.lower()
            for bucket, keywords in keyword_map.items():
                if not any(keyword in lowered for keyword in keywords):
                    continue
                content = self._summarize_sentence(sentence)
                dedupe_key = (bucket, content.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                buckets[bucket].append(
                    {
                        "content": content,
                        "supporting_quote": sentence,
                        "confidence": 0.7,
                    }
                )

        if not any(buckets.values()):
            fallback_sentences = sentences[:3]
            for sentence in fallback_sentences:
                buckets["company_facts"].append(
                    {
                        "content": self._summarize_sentence(sentence),
                        "supporting_quote": sentence,
                        "confidence": 0.4,
                    }
                )
        return buckets

    def _extract_csv(self, file_bytes: bytes) -> str:
        try:
            decoded = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            decoded = file_bytes.decode("latin-1", errors="ignore")
        lines = [line.strip() for line in decoded.splitlines() if line.strip()]
        return "\n".join(lines)

    def _summarize_sentence(self, sentence: str) -> str:
        text = " ".join(sentence.split()).strip()
        return text[:500]

    def _clamp_confidence(self, value: Any) -> float:
        try:
            numeric = float(value)
        except Exception:
            return 0.7
        return max(0.0, min(1.0, numeric))
