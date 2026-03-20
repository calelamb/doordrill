from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.universal_knowledge import UniversalKnowledgeChunk
from app.services.document_processing_service import DocumentProcessingService

logger = logging.getLogger(__name__)

SEED_DOCUMENT_PATH = Path(__file__).parent.parent.parent.parent / "pest_control_d2d_universal_knowledge.md"
CATEGORY_TAG_PATTERN = re.compile(r"^## \[([a-z_]+)\]", re.MULTILINE)
UNIVERSAL_CATEGORIES: set[str] = {
    "intro",
    "objection_handling",
    "reading_homeowner",
    "price_framing",
    "closing",
    "psychology",
    "service_value",
    "competitor_handling",
    "post_pitch",
    "backyard_close",
}


@dataclass(slots=True)
class UniversalChunk:
    category: str
    content: str
    source_tag: str


class UniversalKnowledgeService:
    def __init__(self, *, processing_service: DocumentProcessingService | None = None) -> None:
        self.processing_service = processing_service or DocumentProcessingService()

    def parse_seed_document(self, path: Path | None = None) -> list[UniversalChunk]:
        source = path or SEED_DOCUMENT_PATH
        text = source.read_text(encoding="utf-8")
        raw_sections = re.split(r"\n---\n", text)
        chunks: list[UniversalChunk] = []

        for section in raw_sections:
            section = section.strip()
            if not section:
                continue

            first_line = next((line.strip() for line in section.splitlines() if line.strip()), "")
            if not first_line or (first_line.startswith("#") and not first_line.startswith("## [")):
                continue

            heading_match = CATEGORY_TAG_PATTERN.search(section)
            if heading_match is None:
                continue
            category = heading_match.group(1).strip()
            if category not in UNIVERSAL_CATEGORIES:
                continue

            body_lines: list[str] = []
            heading_consumed = False
            for line in section.splitlines():
                if not heading_consumed and line.startswith("## ["):
                    heading_consumed = True
                    continue
                body_lines.append(line)

            content = "\n".join(body_lines).strip()
            if len(content) < 50:
                continue

            chunks.append(
                UniversalChunk(
                    category=category,
                    content=content,
                    source_tag="industry_standard",
                )
            )

        return chunks

    def seed(self, db: Session, *, force: bool = False) -> int:
        existing_count = int(
            db.scalar(
                select(func.count())
                .select_from(UniversalKnowledgeChunk)
                .where(UniversalKnowledgeChunk.is_active.is_(True))
            )
            or 0
        )
        if existing_count and not force:
            logger.info("universal knowledge already seeded (%d chunks), skipping", existing_count)
            return 0

        chunks = self.parse_seed_document()
        if not chunks:
            raise ValueError("seed document parsed to zero chunks")

        embeddings = self.processing_service.embed_chunks([chunk.content for chunk in chunks])
        if len(embeddings) != len(chunks):
            raise ValueError("embedding count did not match chunk count")

        if force:
            db.execute(delete(UniversalKnowledgeChunk))

        inserted = 0
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            db.add(
                UniversalKnowledgeChunk(
                    category=chunk.category,
                    content=chunk.content,
                    source_tag=chunk.source_tag,
                    is_active=True,
                    embedding=embedding,
                )
            )
            inserted += 1

        db.commit()
        logger.info("universal knowledge seeded: %d chunks", inserted)
        return inserted
