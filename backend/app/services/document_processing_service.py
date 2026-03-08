from __future__ import annotations

import hashlib
import html
import io
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

try:
    from docx import Document as DocxDocument
except Exception:  # pragma: no cover - optional dependency
    DocxDocument = None

EMBEDDING_DIMENSIONS = 1536
EMBEDDING_MODEL = "text-embedding-3-small"
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")


@dataclass
class _Segment:
    text: str
    token_count: int


class DocumentProcessingService:
    def __init__(
        self,
        *,
        storage_service: StorageService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.storage_service = storage_service or StorageService()
        self.settings = settings or get_settings()
        self._encoding = None

    def extract_text(self, file_bytes: bytes, file_type: str, storage_key: str | None = None) -> str:
        normalized = self._normalize_file_type(file_type)
        if normalized == OrgDocumentFileType.PDF:
            return self._extract_pdf(file_bytes)
        if normalized == OrgDocumentFileType.DOCX:
            return self._extract_docx(file_bytes)
        if normalized == OrgDocumentFileType.TXT:
            return self._extract_txt(file_bytes)
        if normalized == OrgDocumentFileType.VIDEO_TRANSCRIPT:
            return self._extract_video_transcript(storage_key or "")
        raise ValueError(f"unsupported file type: {file_type}")

    def count_tokens(self, text: str) -> int:
        return len(self._encode(text))

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        if not normalized:
            return []

        segments = self._build_segments(normalized)
        if not segments:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(segments):
            current: list[_Segment] = []
            current_tokens = 0
            index = start

            while index < len(segments):
                segment = segments[index]
                would_exceed = current and (current_tokens + segment.token_count > chunk_size)
                if would_exceed and current_tokens >= 50:
                    break
                current.append(segment)
                current_tokens += segment.token_count
                index += 1
                if current_tokens >= chunk_size:
                    break

            if not current:
                break

            chunk = " ".join(segment.text for segment in current).strip()
            chunks.append(chunk)
            if index >= len(segments):
                break

            overlap_tokens = 0
            overlap_count = 0
            for segment in reversed(current):
                overlap_tokens += segment.token_count
                overlap_count += 1
                if overlap_tokens >= overlap:
                    break
            start = max(start + 1, index - overlap_count)

        return self._merge_short_trailing_chunk(chunks)

    def embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        if not chunks:
            return []
        if not self.settings.openai_api_key or os.getenv("PYTEST_CURRENT_TEST"):
            return [self._fallback_embedding(chunk) for chunk in chunks]

        url = f"{self.settings.openai_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self.settings.provider_timeout_seconds) as client:
            for start in range(0, len(chunks), 100):
                batch = chunks[start : start + 100]
                response = client.post(
                    url,
                    headers=headers,
                    json={"model": EMBEDDING_MODEL, "input": batch},
                )
                response.raise_for_status()
                body = response.json()
                data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
                if len(data) != len(batch):
                    raise ValueError("embedding response length mismatch")
                vectors.extend([list(item["embedding"]) for item in data])
        return vectors

    def process_document(self, db: Session, *, document_id: str) -> None:
        document = db.scalar(select(OrgDocument).where(OrgDocument.id == document_id))
        if document is None:
            raise ValueError("document not found")

        document.status = OrgDocumentStatus.PROCESSING
        document.error_message = None
        db.flush()

        try:
            file_bytes = self.storage_service.download_bytes(document.storage_key)
            extracted_text = self.extract_text(file_bytes, document.file_type.value, document.storage_key)
            if not extracted_text.strip():
                raise ValueError("document contains no extractable text")

            chunks = self.chunk_text(extracted_text)
            if not chunks:
                raise ValueError("document chunking produced no output")

            embeddings = self.embed_chunks(chunks)
            if len(embeddings) != len(chunks):
                raise ValueError("embedding count did not match chunk count")

            db.execute(delete(OrgDocumentChunk).where(OrgDocumentChunk.document_id == document.id))

            total_tokens = 0
            for chunk_index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                token_count = self.count_tokens(chunk_text)
                total_tokens += token_count
                db.add(
                    OrgDocumentChunk(
                        document_id=document.id,
                        org_id=document.org_id,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        token_count=token_count,
                        embedding=embedding,
                    )
                )

            document.status = OrgDocumentStatus.READY
            document.chunk_count = len(chunks)
            document.token_count = total_tokens
            document.error_message = None
            db.commit()
        except Exception as exc:
            db.rollback()
            failed_document = db.scalar(select(OrgDocument).where(OrgDocument.id == document_id))
            if failed_document is not None:
                failed_document.status = OrgDocumentStatus.FAILED
                failed_document.error_message = str(exc)
                db.commit()
            raise

    def run_background_task(self, document_id: str) -> None:
        db = SessionLocal()
        try:
            self.process_document(db, document_id=document_id)
        except Exception:
            logger.exception("document processing failed", extra={"document_id": document_id})
        finally:
            db.close()

    def _normalize_file_type(self, file_type: str | OrgDocumentFileType) -> OrgDocumentFileType:
        if isinstance(file_type, OrgDocumentFileType):
            return file_type
        return OrgDocumentFileType(str(file_type).lower())

    def _extract_pdf(self, file_bytes: bytes) -> str:
        if PdfReader is not None:
            reader = PdfReader(io.BytesIO(file_bytes))
            text = "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
            if text:
                return text

        decoded = file_bytes.decode("latin-1", errors="ignore")
        matches = re.findall(r"\((.*?)\)\s*Tj", decoded, re.DOTALL)
        text = " ".join(match.replace("\\(", "(").replace("\\)", ")") for match in matches)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_docx(self, file_bytes: bytes) -> str:
        if DocxDocument is not None:
            document = DocxDocument(io.BytesIO(file_bytes))
            text = "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
            if text:
                return text

        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        matches = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml)
        return re.sub(r"\s+", " ", html.unescape(" ".join(matches))).strip()

    def _extract_txt(self, file_bytes: bytes) -> str:
        try:
            return file_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1", errors="ignore").strip()

    def _extract_video_transcript(self, storage_key: str) -> str:
        logger.warning("video transcript extraction is not implemented yet", extra={"storage_key": storage_key})
        return ""

    def _build_segments(self, text: str) -> list[_Segment]:
        raw_sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
        segments: list[_Segment] = []
        for sentence in raw_sentences:
            token_count = self.count_tokens(sentence)
            if token_count <= 600:
                segments.append(_Segment(sentence, token_count))
                continue
            segments.extend(self._split_oversized_sentence(sentence))
        return segments

    def _split_oversized_sentence(self, sentence: str) -> list[_Segment]:
        clause_parts = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]
        if len(clause_parts) > 1:
            segments = [_Segment(part, self.count_tokens(part)) for part in clause_parts]
            if all(segment.token_count <= 600 for segment in segments):
                return segments

        tokens = self._encode(sentence)
        segments: list[_Segment] = []
        start = 0
        while start < len(tokens):
            window = tokens[start : start + 500]
            text = self._decode(window).strip()
            if text:
                segments.append(_Segment(text, len(window)))
            start += 450
        return segments

    def _merge_short_trailing_chunk(self, chunks: list[str]) -> list[str]:
        if len(chunks) < 2:
            return chunks
        trailing = chunks[-1]
        if self.count_tokens(trailing) >= 50:
            return chunks
        merged = f"{chunks[-2]} {trailing}".strip()
        if self.count_tokens(merged) <= 600:
            return [*chunks[:-2], merged]
        return chunks

    def _encode(self, text: str):
        if tiktoken is not None:
            if self._encoding is None:
                self._encoding = tiktoken.get_encoding("cl100k_base")
            return self._encoding.encode(text)
        return TOKEN_PATTERN.findall(text)

    def _decode(self, tokens) -> str:
        if tiktoken is not None:
            if self._encoding is None:
                self._encoding = tiktoken.get_encoding("cl100k_base")
            return self._encoding.decode(tokens)

        out: list[str] = []
        for token in tokens:
            if not out:
                out.append(token)
                continue
            if re.match(r"[^\w\s]", token):
                out[-1] = f"{out[-1]}{token}"
            else:
                out.append(token)
        return " ".join(out)

    def _fallback_embedding(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        while len(values) < EMBEDDING_DIMENSIONS:
            seed = hashlib.sha256(seed + text[:128].encode("utf-8")).digest()
            values.extend(((byte / 255.0) * 2.0) - 1.0 for byte in seed)
        return values[:EMBEDDING_DIMENSIONS]
