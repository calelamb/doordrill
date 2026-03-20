# PRD: Universal RAG Knowledge Base — v1
**For:** Codex
**Owner:** Cale
**Status:** Ready for Implementation
**Touches:** `document_retrieval_service.py`, `conversation_orchestrator.py`, new migration, new model, new seed loader, new admin endpoint

---

## Background

The drill currently retrieves knowledge only from org-specific uploaded documents. When a new org signs up, they have no knowledge base — zero RAG context in the LLM prompt. This means the homeowner persona has no grounding in actual D2D pest control sales patterns, terminology, or objection flows.

The solution is a two-layer RAG system:

1. **Universal layer** — a company-agnostic seed knowledge base covering D2D pest control techniques, common objections, homeowner psychology, and industry language. All orgs inherit this automatically. No upload required.

2. **Org-specific layer** — the company's own uploaded training material (scripts, playbooks, product sheets). This already exists. It adds company-specific context on top of the universal base.

When a session runs, retrieval queries both layers and merges results. Org-specific chunks take priority — if both layers have relevant content, the org-specific content appears first and the universal content fills remaining slots.

---

## Feature Specs

---

### R-01: Universal Knowledge Chunk Model

**Problem:** No database table exists for universal (org-agnostic) knowledge chunks.

**File:** New migration + `app/models/universal_knowledge.py`

**What to Build:**

New `UniversalKnowledgeChunk` model:

```python
class UniversalKnowledgeChunk(Base):
    __tablename__ = "universal_knowledge_chunks"
    __table_args__ = (
        Index("ix_universal_knowledge_chunks_category", "category"),
        Index("ix_universal_knowledge_chunks_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_tag: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingVector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

Field definitions:
- `category`: semantic bucket — one of `intro`, `objection_handling`, `reading_homeowner`, `price_framing`, `closing`, `psychology`, `service_value`, `competitor_handling`, `post_pitch`, `backyard_close`
- `source_tag`: human-readable origin — e.g., `"industry_standard"`, `"ecoshield_derived"`, `"d2d_expert_synthesis"`
- `is_active`: allows deactivating chunks without deletion (future: A/B testing, per-vertical filtering)
- `embedding`: same `EmbeddingVector(1536)` type used in existing models

Use the same `EmbeddingVector` typedef from `app/models/knowledge.py` (import it, don't re-declare).

Migration: `alembic revision --autogenerate -m "add universal_knowledge_chunks table"`. Include the pgvector extension guard already used in existing migrations.

**Acceptance Criteria:**
- `universal_knowledge_chunks` table exists after migration
- `category`, `is_active`, `embedding` indexed
- Model importable from `app.models.universal_knowledge`

---

### R-02: Seed Loader — Parse and Embed the Universal Knowledge Document

**Problem:** The seed knowledge document (`pest_control_d2d_universal_knowledge.md`) exists as a markdown file but has not been parsed into chunks, embedded, or loaded into the database.

**File:** `app/services/universal_knowledge_service.py` (new)

**What to Build:**

A `UniversalKnowledgeService` with two responsibilities:

1. **Parse** the seed markdown into structured chunks
2. **Seed** the database — embed chunks and insert into `universal_knowledge_chunks`

```python
SEED_DOCUMENT_PATH = Path(__file__).parent.parent.parent.parent / "pest_control_d2d_universal_knowledge.md"

CATEGORY_TAG_PATTERN = re.compile(r"\[([a-z_]+)\]")

class UniversalKnowledgeService:
    def __init__(self, *, processing_service: DocumentProcessingService | None = None) -> None:
        self.processing_service = processing_service or DocumentProcessingService()

    def parse_seed_document(self, path: Path | None = None) -> list[UniversalChunk]:
        """Parse the markdown seed doc into (category, content, source_tag) triples."""
        source = path or SEED_DOCUMENT_PATH
        text = source.read_text(encoding="utf-8")
        raw_sections = re.split(r"\n---\n", text)
        chunks: list[UniversalChunk] = []
        for section in raw_sections:
            section = section.strip()
            if not section or section.startswith("#"):
                continue
            # Extract category from [category] tag in heading
            heading_match = re.search(r"^## \[([a-z_]+)\]", section, re.MULTILINE)
            category = heading_match.group(1) if heading_match else "general"
            # Remove the heading line, keep body
            body_lines = [line for line in section.splitlines() if not line.startswith("## [")]
            content = "\n".join(body_lines).strip()
            if len(content) < 50:
                continue
            chunks.append(UniversalChunk(category=category, content=content, source_tag="industry_standard"))
        return chunks

    def seed(self, db: Session, *, force: bool = False) -> int:
        """Embed and insert universal chunks. Skip if already seeded unless force=True."""
        existing_count = db.scalar(select(func.count()).select_from(UniversalKnowledgeChunk).where(
            UniversalKnowledgeChunk.is_active == True
        ))
        if existing_count and not force:
            logger.info("universal knowledge already seeded (%d chunks), skipping", existing_count)
            return 0

        chunks = self.parse_seed_document()
        if not chunks:
            raise ValueError("seed document parsed to zero chunks")

        texts = [chunk.content for chunk in chunks]
        embeddings = self.processing_service.embed_chunks(texts)

        inserted = 0
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            db.add(UniversalKnowledgeChunk(
                category=chunk.category,
                content=chunk.content,
                source_tag=chunk.source_tag,
                is_active=True,
                embedding=embedding,
            ))
            inserted += 1

        db.commit()
        logger.info("universal knowledge seeded: %d chunks", inserted)
        return inserted
```

Add `@dataclass class UniversalChunk: category: str; content: str; source_tag: str`.

**Acceptance Criteria:**
- `UniversalKnowledgeService().parse_seed_document()` returns ≥ 15 chunks from the seed doc
- Each chunk has a valid category from the known set
- `seed()` is idempotent — calling it twice without `force=True` does not re-insert
- `seed(db, force=True)` clears and re-inserts all chunks
- `test_universal_knowledge_service.py` tests: parse returns ≥ 15 chunks, idempotency, force flag

---

### R-03: Auto-Seed on Startup

**Problem:** The seed must run before any session can use universal knowledge. Manually running a script is fragile.

**File:** `app/main.py` (or wherever FastAPI `startup` event is registered)

**What to Build:**

Add a startup event handler that runs the seed in a background thread so it doesn't block server startup:

```python
@app.on_event("startup")
async def seed_universal_knowledge() -> None:
    def _seed() -> None:
        db = SessionLocal()
        try:
            svc = UniversalKnowledgeService()
            count = svc.seed(db)
            if count:
                logger.info("startup: seeded %d universal knowledge chunks", count)
        except Exception:
            logger.exception("startup: universal knowledge seed failed (non-fatal)")
        finally:
            db.close()

    asyncio.get_event_loop().run_in_executor(None, _seed)
```

Seed failure is non-fatal — the server starts regardless. If embedding is unavailable (no OpenAI key), chunks are stored without embeddings and keyword retrieval is used as fallback.

Also expose an admin endpoint for manual re-seeding:

```
POST /admin/universal-knowledge/seed
Body: { "force": true }
Response: { "inserted": 18 }
```

This endpoint should be protected by the existing admin auth (or `is_superuser` check — follow the pattern already used in admin routes).

**Acceptance Criteria:**
- Server starts successfully even if seeding fails
- Admin endpoint `POST /admin/universal-knowledge/seed?force=true` triggers reseed
- Calling the seed endpoint twice without force returns `{"inserted": 0}`

---

### R-04: Universal Retrieval — Query Universal Layer Alongside Org-Specific

**Problem:** `DocumentRetrievalService.retrieve()` and `retrieve_for_topic()` only query org-specific documents. Universal chunks in `universal_knowledge_chunks` are never queried.

**File:** `app/services/document_retrieval_service.py`

**What to Build:**

Add `_retrieve_universal_python()` method that queries `UniversalKnowledgeChunk` using cosine similarity:

```python
def _retrieve_universal_python(
    self,
    db: Session,
    *,
    query_vector: list[float],
    k: int,
) -> list[RetrievedChunk]:
    rows = db.execute(
        select(UniversalKnowledgeChunk)
        .where(UniversalKnowledgeChunk.is_active == True)
        .where(UniversalKnowledgeChunk.embedding.is_not(None))
    ).scalars().all()

    scored: list[RetrievedChunk] = []
    for chunk in rows:
        similarity = self._cosine_similarity(query_vector, chunk.embedding or [])
        scored.append(RetrievedChunk(
            chunk_id=str(chunk.id),
            document_id="universal",
            document_name=f"Industry Knowledge [{chunk.category}]",
            text=chunk.content,
            similarity_score=similarity,
            is_universal=True,  # new field — see R-05
        ))
    scored.sort(key=lambda r: r.similarity_score, reverse=True)
    return scored[:k]
```

Update `retrieve()` and `retrieve_for_topic()` to merge universal results:

```python
# At the end of both retrieve methods, after org-specific rows are gathered:
universal_rows = self._retrieve_universal_python(db, query_vector=query_vector, k=k)
rows = self._merge_with_universal(org_rows=rows, universal_rows=universal_rows, k=k)
```

**Merge logic** (`_merge_with_universal`):
- Org-specific rows keep their position — they are always preferred
- Universal rows fill remaining slots up to `k` total
- Universal rows below `min_score` are excluded
- A universal row is excluded if an org-specific row with the same category already occupies the result (prevents duplication of topic coverage)

```python
def _merge_with_universal(
    self,
    *,
    org_rows: list[RetrievedChunk],
    universal_rows: list[RetrievedChunk],
    k: int,
    min_score: float = 0.70,
) -> list[RetrievedChunk]:
    result = list(org_rows)
    occupied_categories: set[str] = {
        r.document_name.split("[")[-1].rstrip("]")
        for r in org_rows
        if "Industry Knowledge" not in r.document_name
    }
    for universal in universal_rows:
        if len(result) >= k:
            break
        if universal.similarity_score < min_score:
            continue
        # Extract category from document_name e.g. "Industry Knowledge [closing]"
        cat = universal.document_name.split("[")[-1].rstrip("]")
        if cat in occupied_categories:
            continue
        result.append(universal)
    return result
```

**Acceptance Criteria:**
- When an org has no documents, `retrieve()` still returns universal chunks
- When an org has documents, universal chunks only fill slots not covered by org-specific content
- Org-specific chunks always appear before universal chunks in the merged result
- Universal chunks with similarity < `min_score` are excluded
- `test_document_retrieval_service.py` has a test: org with no docs → universal chunks returned; org with matching docs → org-specific chunks take priority

---

### R-05: RetrievedChunk — Add `is_universal` Flag

**Problem:** The prompt layer needs to know whether a chunk is universal or org-specific so it can label them differently.

**File:** `app/schemas/knowledge.py`

**What to Build:**

Add `is_universal: bool = False` to `RetrievedChunk`:

```python
class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    similarity_score: float
    is_universal: bool = False
```

No migration needed — this is a schema-only change.

**Acceptance Criteria:**
- `RetrievedChunk` has `is_universal` field defaulting to `False`
- All existing callers of `RetrievedChunk(...)` still work (field has default)
- Universal chunks returned by `_retrieve_universal_python` have `is_universal=True`

---

### R-06: Prompt Formatting — Distinguish Universal vs. Org-Specific Context

**Problem:** `format_for_prompt()` labels all chunks as `=== Company Training Material ===`. Universal chunks should be labeled differently so the LLM doesn't mistake them for company-specific instructions.

**File:** `app/services/document_retrieval_service.py` → `format_for_prompt()`

**What to Build:**

Split the formatted output into two blocks — org-specific first, universal second:

```python
def format_for_prompt(self, chunks: list[RetrievedChunk], max_tokens: int = 1200) -> str:
    org_chunks = [c for c in chunks if not c.is_universal]
    universal_chunks = [c for c in chunks if c.is_universal]

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
```

Extract the existing formatting logic into `_format_chunk_block(chunks, header, footer, token_budget) -> tuple[str, int]` to avoid duplication.

The LLM already receives this block in Layer 5 of the prompt. No prompt template changes needed — the headers are self-explanatory.

**Acceptance Criteria:**
- Org-specific chunks appear under `=== Company Training Material ===`
- Universal chunks appear under `=== Industry Sales Knowledge ===`
- Total token budget is respected across both blocks
- If only universal chunks exist, only the industry block appears
- If only org-specific chunks exist, behavior is unchanged from current

---

### R-07: Org-Specific Material Upload — Enterprise Overlay Path

**Problem:** The enterprise upload flow works but there is no guidance for what makes good org-specific material vs. what the universal layer already covers. Without this, companies upload redundant content and miss the high-value gap-filling use cases.

**File:** `app/api/routes/knowledge.py` (upload endpoint response) + new `UNIVERSAL_CATEGORIES` constant in `universal_knowledge_service.py`

**What to Build:**

1. Add `UNIVERSAL_CATEGORIES` constant listing what the universal layer covers:

```python
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
```

2. After document upload completes, add an `upload_tips` field to the response indicating what topics the universal layer already covers and what the org's specific content adds:

```python
class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    chunk_count: int | None = None
    universal_layer_active: bool = True
    universal_categories_covered: list[str] = field(default_factory=list)
```

`universal_categories_covered` is populated from `UNIVERSAL_CATEGORIES`. This tells the manager dashboard what base knowledge already exists so they know what to upload next.

3. In the manager dashboard (future sprint, noted here): show a "Knowledge Coverage" indicator listing universal categories vs. org-specific categories to help managers understand what gaps their uploads are filling.

**Acceptance Criteria:**
- `DocumentUploadResponse` includes `universal_layer_active: True` and `universal_categories_covered` list
- `UNIVERSAL_CATEGORIES` constant defined in `universal_knowledge_service.py`
- No behavior change to existing upload flow

---

## Implementation Notes

### Priority Order

1. **R-01** — Model + migration. Unblocks everything else. 20 minutes.
2. **R-02** — Seed loader. Can be tested standalone with no embeddings (fallback). 30 minutes.
3. **R-05** — `RetrievedChunk.is_universal` field. 5 minutes.
4. **R-04** — Universal retrieval. Core of the feature. 45 minutes.
5. **R-06** — Prompt formatting split. 20 minutes.
6. **R-03** — Auto-seed on startup + admin endpoint. 20 minutes.
7. **R-07** — Upload response enhancement. 15 minutes. Low priority — polish.

### Files Touched

| Feature | Primary File | Secondary |
|---|---|---|
| R-01 Model | `app/models/universal_knowledge.py` (new) | Alembic migration |
| R-02 Seed loader | `app/services/universal_knowledge_service.py` (new) | seed doc (already exists) |
| R-03 Startup + admin | `app/main.py` | `app/api/routes/admin.py` |
| R-04 Retrieval | `app/services/document_retrieval_service.py` | |
| R-05 Schema | `app/schemas/knowledge.py` | |
| R-06 Formatting | `app/services/document_retrieval_service.py` | |
| R-07 Upload response | `app/api/routes/knowledge.py` | `universal_knowledge_service.py` |

### Do Not Change

- `OrgDocument`, `OrgDocumentChunk`, `OrgKnowledgeDoc`, `OrgMaterial` models — no nullable changes to org_id
- Existing `format_for_prompt` public signature — only the implementation changes
- `RetrievedChunk` existing fields — only adding `is_universal: bool = False`
- `retrieve()` min_score threshold (0.70) — this applies to both org and universal chunks

### Architecture Decisions

**Why a new table instead of nullable `org_id` on existing tables?**
The existing `OrgDocument` and `OrgKnowledgeDoc` tables have non-nullable FK constraints to `organizations.id`. Making them nullable would require changes across models, migrations, and retrieval queries — risky scope. A dedicated `UniversalKnowledgeChunk` table is isolated, schema-clean, and clearly communicates intent. Universal knowledge is not "an org with no ID" — it's a fundamentally different construct.

**Why not a separate vector store (Pinecone, Weaviate)?**
All existing retrieval runs against Postgres with pgvector. Introducing a second vector store creates operational complexity (two services to monitor, two embedding pipelines, two auth systems) for a relatively small knowledge base (~20-50 chunks). The universal layer is small enough that Python-side cosine similarity scan is acceptable. If the universal knowledge base grows beyond 5,000 chunks, migrate to pgvector index query.

**Why `min_score` applies to universal chunks?**
Without a similarity gate, the universal layer would always contribute chunks even when they're irrelevant. A universal chunk about "backyard close technique" should not appear when the query is about competitor pricing. The same 0.70 threshold used for org-specific retrieval applies.

### Seed Document Location

`pest_control_d2d_universal_knowledge.md` — in the repo root alongside the PRDs.

The seed loader reads this file relative to its own path. It is version-controlled alongside the code. To update universal knowledge: edit the markdown, run `POST /admin/universal-knowledge/seed?force=true`, done.

---

## What This Unlocks

- **Day 1 orgs** — Any new company that signs up immediately has a working knowledge base without uploading anything. The homeowner persona has real D2D pest control context from the first drill.
- **Differentiated orgs** — Companies with their own uploaded material get org-specific answers prioritized, with universal knowledge filling gaps. The two layers are complementary, not competing.
- **Iterative knowledge improvement** — The seed document is a markdown file in version control. Updating it and re-seeding is a one-command operation. No database manipulation required.
- **Future verticals** — The `category` and `source_tag` fields on `UniversalKnowledgeChunk` allow filtering by vertical when DoorDrill expands beyond pest control (roofing, windows, solar). Each vertical gets its own set of active chunks.
