# PRD: RAG Knowledge Base — Company Training Material Ingestion
**Version:** 1.0
**Status:** Ready for Codex implementation
**Depends on:** Core backend (auth, storage service), Grading Engine V2 (G1–G3), Manager AI Coaching (C1–C3)

---

## What This PRD Builds

Every D2D sales company has its own scripts, objection playbooks, training manuals, onboarding videos, and methodology guides. Right now DoorDrill ignores all of it — the AI homeowner uses generic personas, the grading rubric is generic, and coaching recommendations are generic. This PRD makes DoorDrill org-aware at the AI level.

When a manager uploads their training material, that content becomes the ground truth for:
- **Grading**: "Does this rep's response align with our company's objection-handling methodology?"
- **Homeowner simulation**: "What specific objections would a homeowner in our territory actually raise?"
- **Coaching**: "According to your training manual, here's what Marcus should have said at that moment."
- **Direct Q&A**: "What does our script say about handling the price-per-month objection?"

The architecture is RAG (Retrieval Augmented Generation): documents are chunked, embedded, and stored in pgvector. At inference time, the most relevant chunks are retrieved and injected into prompts as context. No fine-tuning required. No custom ML infrastructure.

---

## Architecture Overview

```
Manager uploads file (PDF/DOCX/TXT/video)
    ↓
[R1] Document processing pipeline
    — text extraction (PyPDF2, python-docx, Whisper)
    — semantic chunking (500 tokens, 50-token overlap)
    — embedding generation (OpenAI text-embedding-3-small)
    — pgvector storage (per-org, per-document)
    ↓
[R2] Retrieval service
    — cosine similarity search via pgvector
    — query → top-k chunks with scores
    — org-scoped isolation
    ↓
Injection points:
[R3] Grading prompts        — "Our methodology says X"
[R4] Homeowner simulation   — "In our territory, homeowners raise Y"
[R5] Manager coaching       — "Your training material says Z"
[R6] Document management UI — upload, status, delete
[R7] Direct Q&A interface   — "Ask your training material"
```

---

## Database: pgvector Setup

Before Phase R1, the database must have the `vector` extension enabled. This is handled in the R1 migration.

**pgvector dependency:** `pip install pgvector` + `psycopg2` or `asyncpg`. The SQLAlchemy integration uses `pgvector.sqlalchemy.Vector`.

**Embedding model:** `text-embedding-3-small` (1536 dimensions, $0.02 per 1M tokens — a 100-page manual costs ~$0.01 to embed).

**Index type:** HNSW (`lists=100`, `ef_construction=200`) for fast approximate nearest-neighbor search. Falls back to exact IVFFlat if HNSW not available.

---

## Models to Create

### `OrgDocument` (`org_documents` table)
```
id                  String PK
org_id              FK → orgs.id (CASCADE)
name                String — display name
original_filename   String — uploaded filename
file_type           Enum(pdf, docx, txt, video_transcript)
storage_key         String — path in storage service
status              Enum(pending, processing, ready, failed)
chunk_count         Integer nullable
token_count         Integer nullable
error_message       Text nullable
uploaded_by         FK → users.id
created_at, updated_at
```

### `OrgDocumentChunk` (`org_document_chunks` table)
```
id                  String PK
document_id         FK → org_documents.id (CASCADE)
org_id              String (denormalized for fast scoped queries)
chunk_index         Integer
text                Text — raw chunk content
token_count         Integer
embedding           Vector(1536) — pgvector column
created_at
```
Index: HNSW on `embedding` column, scoped queries by `org_id`.

---

## Phase R1 — Document Upload + Processing Pipeline

### Goals

1. **Create models** `OrgDocument` and `OrgDocumentChunk` in `backend/app/models/knowledge.py`. Add Alembic migration that:
   - Enables `CREATE EXTENSION IF NOT EXISTS vector`
   - Creates `org_documents` and `org_document_chunks` tables
   - Creates HNSW index: `CREATE INDEX ON org_document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=200)`

2. **Create `backend/app/services/document_processing_service.py`** with `DocumentProcessingService` class:
   - `extract_text(file_bytes, file_type) -> str` — dispatch to:
     - `_extract_pdf(file_bytes)` using `PyPDF2` (or `pypdf`)
     - `_extract_docx(file_bytes)` using `python-docx`
     - `_extract_txt(file_bytes)` — decode UTF-8
     - `_extract_video_transcript(storage_key)` — stub that returns `""` with a log warning (Whisper integration is Phase R1 stretch goal)
   - `chunk_text(text, chunk_size=500, overlap=50) -> list[str]` — token-aware chunking using `tiktoken` (cl100k_base). Each chunk must be between 50 and 600 tokens. Respect sentence boundaries — never split mid-sentence.
   - `embed_chunks(chunks: list[str]) -> list[list[float]]` — call OpenAI embeddings API in batches of 100. Use `text-embedding-3-small`. Return list of 1536-dimensional vectors.
   - `process_document(db, *, document_id: str) -> None` — full pipeline:
     1. Load `OrgDocument`, set `status=processing`
     2. Download file bytes from storage service using `document.storage_key`
     3. Extract text
     4. Chunk text
     5. Embed chunks in batches
     6. Write `OrgDocumentChunk` rows with embeddings
     7. Update `OrgDocument`: `status=ready`, `chunk_count=N`, `token_count=N`
     8. On any exception: set `status=failed`, `error_message=str(exc)`, re-raise

3. **Add upload endpoint** to `backend/app/api/manager.py`:
   ```
   POST /manager/documents
   Accepts: multipart/form-data with fields: file (UploadFile), name (str), manager_id (str)
   ```
   - Validate file type by extension (pdf, docx, txt only in R1)
   - Upload file bytes to storage service → get `storage_key`
   - Create `OrgDocument` row with `status=pending`
   - Dispatch `process_document` as a background task (use FastAPI `BackgroundTasks`)
   - Return `OrgDocumentResponse` immediately (don't wait for processing)

4. **Add management endpoints** to `backend/app/api/manager.py`:
   ```
   GET  /manager/documents?manager_id=...     — list all org documents with status
   GET  /manager/documents/{document_id}      — get single document details
   DELETE /manager/documents/{document_id}    — delete document + all chunks
   ```

5. **Add schemas** to `backend/app/schemas/knowledge.py`:
   - `OrgDocumentResponse` (id, name, original_filename, file_type, status, chunk_count, token_count, error_message, created_at)
   - `OrgDocumentListResponse` (documents: list[OrgDocumentResponse])

6. **Install dependencies** in `backend/pyproject.toml` or `requirements.txt`:
   - `pgvector` — SQLAlchemy integration for Vector column type
   - `pypdf` — PDF text extraction
   - `python-docx` — DOCX extraction
   - `tiktoken` — token counting and chunk splitting

7. **Tests:**
   - `test_document_upload_and_processing.py`:
     - Upload a small in-memory PDF (use `reportlab` or a raw PDF fixture)
     - Assert `OrgDocument` row created with `status=pending`, then transitions to `ready`
     - Assert `OrgDocumentChunk` rows exist with non-null embeddings (mock the OpenAI embeddings call)
   - `test_document_chunking.py`:
     - Unit test `chunk_text()` directly: assert no chunk exceeds 600 tokens, assert overlap is preserved, assert sentence boundaries respected
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase R2 — Retrieval Service

### Goals

1. **Create `backend/app/services/document_retrieval_service.py`** with `DocumentRetrievalService` class:
   - `retrieve(db, *, org_id: str, query: str, k: int = 5, min_score: float = 0.70) -> list[RetrievedChunk]`
     - Embed the query string using `text-embedding-3-small`
     - Run pgvector cosine similarity search:
       ```sql
       SELECT chunk.id, chunk.text, chunk.document_id, doc.name,
              1 - (chunk.embedding <=> :query_vector) AS similarity
       FROM org_document_chunks chunk
       JOIN org_documents doc ON doc.id = chunk.document_id
       WHERE chunk.org_id = :org_id AND doc.status = 'ready'
       ORDER BY chunk.embedding <=> :query_vector
       LIMIT :k
       ```
     - Filter results below `min_score` threshold
     - Return list of `RetrievedChunk` (chunk_id, document_id, document_name, text, similarity_score)
   - `retrieve_for_topic(db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5) -> list[RetrievedChunk]`
     - Combines `topic` and `context_hint` into a rich query string
     - Wraps `retrieve()` with sensible defaults for topic-based lookups
   - `format_for_prompt(chunks: list[RetrievedChunk], max_tokens: int = 1200) -> str`
     - Format retrieved chunks as a clean prompt section:
       ```
       === Company Training Material ===
       [From: {document_name}]
       {chunk_text}

       [From: {document_name}]
       {chunk_text}
       === End Company Training Material ===
       ```
     - Truncate to `max_tokens` total if needed (trim last chunk, not mid-word)
   - Cache embeddings for identical queries with TTL 15 minutes (use `ManagementCacheService`)
   - If org has no documents, return empty list immediately (zero latency penalty)

2. **Add `RetrievedChunk` dataclass** to `backend/app/schemas/knowledge.py`

3. **Add direct Q&A endpoint** to `backend/app/api/manager.py`:
   ```
   POST /manager/documents/query
   Body: {"manager_id": str, "query": str, "k": int = 5}
   Returns: {"chunks": [RetrievedChunk], "has_documents": bool}
   ```
   This endpoint lets the frontend build the Q&A interface without needing a separate LLM call — the manager can read the raw retrieved chunks.

4. **Tests:**
   - `test_document_retrieval.py`:
     - Seed an `OrgDocument` with 3 `OrgDocumentChunk` rows with known embeddings (use pre-computed test vectors)
     - Call `retrieve()` with a query whose embedding is closest to chunk 2
     - Assert chunk 2 is returned first with similarity > 0.7
     - Assert org isolation: chunks from a different org are not returned
   - `test_retrieval_empty_org.py`:
     - Call `retrieve()` on an org with no documents, assert returns `[]` in < 10ms
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase R3 — Grading Injection

### Goals

1. **Modify `GradingService.grade_session()`** in `backend/app/services/grading_service.py`:
   - After loading the active `PromptVersion`, call `DocumentRetrievalService().retrieve_for_topic()` with:
     - `org_id` from the session's org (look up via `session.rep → user.org_id`)
     - `topic` = `"sales rubric objection handling closing technique grading methodology"`
     - `context_hint` = the scenario name + difficulty level
     - `k=4`, `min_score=0.72`
   - If chunks are returned, inject formatted chunks into the grading prompt as a new section before the rubric:
     ```
     {existing_prompt_template}

     {formatted_company_context}

     Use the company training material above to interpret whether the rep's responses align
     with their specific methodology. Weight company-specific technique guidance over generic
     best practices when they conflict.
     ```
   - If no chunks returned (org has no documents), grading runs exactly as before — zero regression

2. **No schema changes required** — `GradingRun` already stores `raw_llm_response` and prompt is captured in `PromptVersion`

3. **Tests:**
   - `test_grading_uses_company_context.py`:
     - Seed org with an `OrgDocumentChunk` about objection handling
     - Run grading on a session from that org
     - Assert the captured prompt in `GradingRun.raw_llm_response` contains "Company Training Material" section
   - `test_grading_without_documents_unchanged.py`:
     - Run grading on a session from an org with no documents
     - Assert grading completes normally, no error, no injection section
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase R4 — Homeowner Simulation Injection

### Goals

The AI homeowner in `ConversationOrchestrator` currently uses a generic persona built from `scenario.persona` JSON. This phase makes it org-aware: when a rep starts a drill, the homeowner AI gets context from that org's uploaded territory/objection materials.

1. **Modify `ConversationOrchestrator._build_system_prompt()`** (or equivalent session initialization method) in `backend/app/services/conversation_orchestrator.py`:
   - At session start, call `DocumentRetrievalService().retrieve_for_topic()` with:
     - `org_id` from the session's org
     - `topic` = `"homeowner objections territory D2D door to door sales typical concerns"`
     - `context_hint` = f"{scenario.persona.get('attitude', '')} homeowner {scenario.industry} {' '.join(scenario.persona.get('concerns', []))}"
     - `k=3`, `min_score=0.70`
   - Inject as an additional section in the homeowner system prompt:
     ```
     {existing_homeowner_system_prompt}

     === Territory & Objection Context (from your company's training materials) ===
     {formatted_chunks}

     Draw on the above when deciding how to respond to the rep's pitch. These are real
     objections and concerns from your specific market — use them to make the simulation
     more realistic and representative.
     ```
   - If no chunks returned, homeowner behavior is unchanged

2. **Pass `db` session and `org_id` into the orchestrator** if not already available. Check `backend/app/voice/ws.py` to confirm the WebSocket handler has org context — if not, look up org via `session.rep_id → User.org_id` at session initialization.

3. **Tests:**
   - `test_homeowner_uses_company_objections.py`:
     - Seed org with a document chunk describing a specific objection pattern
     - Initialize a conversation session for that org
     - Assert the orchestrator's system prompt contains the injected territory context
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase R5 — Coaching Injection

### Goals

The manager AI coaching service (`ManagerAiCoachingService`) currently generates coaching recommendations based purely on score data. This phase adds company-methodology grounding: coaching advice references what the company actually teaches.

1. **Modify `generate_rep_insight()`** in `ManagerAiCoachingService`:
   - After building skill profile and weakness data, call `DocumentRetrievalService().retrieve_for_topic()` with:
     - `org_id` from `rep.org_id`
     - `topic` = f"coaching {' '.join(top_weakness_tags)} technique improvement"
     - `k=3`, `min_score=0.68`
   - If chunks returned, add to prompt:
     ```
     Company training material relevant to this rep's weak areas:
     {formatted_chunks}

     When writing the coaching_script, reference what the company's own material says
     about improving these skills. Quote or paraphrase it specifically — don't give generic advice.
     ```

2. **Modify `generate_one_on_one_prep()`** similarly:
   - Retrieve with `topic` = f"1:1 coaching {' '.join(adaptive_plan.get('weakest_skills', []))} conversation technique"
   - Inject into the prep prompt with the same framing

3. **Modify `answer_manager_chat()`**:
   - When `relevant_data` is assembled in the API endpoint before being passed to `answer_manager_chat`, retrieve relevant chunks based on the classified intent and inject them into the `relevant_data` dict under key `"company_training_context"`
   - The chat prompt already serializes `relevant_data` — this flows automatically

4. **Tests:**
   - `test_coaching_uses_company_material.py`:
     - Seed org with a document chunk about a specific closing technique
     - Call `generate_rep_insight()` for a rep with low closing scores
     - Assert the prompt context includes the closing technique chunk
   - `pytest tests/ -x -q` — all tests must pass

---

## Phase R6 — Document Management UI

### Goals

Managers need a place to upload, view status, and delete their training materials. This should feel like a clean settings panel, not an afterthought.

1. **Create `dashboard/src/pages/KnowledgeBasePage.tsx`**:
   - Layout: header ("Training Materials"), upload zone, document list
   - **Upload zone**: Drag-and-drop + click-to-browse. Accepts `.pdf`, `.docx`, `.txt`. Shows filename + size before upload. On submit: `POST /manager/documents`. Shows upload progress.
   - **Document list**: Table or card list. Columns: Name, Type (icon), Status (chip: Processing / Ready / Failed), Chunks, Uploaded, Actions.
   - **Status chips**:
     - `pending` / `processing` → amber spinner chip, auto-refreshes every 5s
     - `ready` → green chip with chunk count ("142 chunks")
     - `failed` → red chip with tooltip showing `error_message`
   - **Delete action**: Confirm modal → `DELETE /manager/documents/{id}`. Remove from list on success.
   - **Empty state**: "Upload your training scripts, objection playbooks, or methodology guides. The AI will use them to grade your reps and personalize coaching."
   - Handle loading, error, and empty states

2. **Create `dashboard/src/components/DocumentUploadZone.tsx`**:
   - Standalone drag-and-drop component using native HTML5 drag events (no external library)
   - Shows accepted file types, max size warning (25MB)
   - Emits `onFileSelected(file: File)` callback
   - Visual states: idle, drag-over, uploading (with progress bar), success, error

3. **Add route** to the dashboard router: `/knowledge-base` → `KnowledgeBasePage`

4. **Add navigation link** in the sidebar or nav bar: "Knowledge Base" with a book/document icon

5. **Create `dashboard/src/lib/knowledge.ts`** API client functions:
   - `uploadDocument(file, name, managerId)` — multipart POST with progress tracking
   - `listDocuments(managerId)` — GET list
   - `deleteDocument(documentId, managerId)` — DELETE
   - `queryDocuments(managerId, query)` — POST query endpoint

---

## Phase R7 — Direct Q&A Interface

### Goals

A manager should be able to ask a natural language question directly against their uploaded materials. "What does our playbook say about handling the 'I already have pest control' objection?" and get back the actual relevant passages.

1. **Create `dashboard/src/components/KnowledgeBaseQueryPanel.tsx`**:
   - Search bar with submit button
   - On submit: `POST /manager/documents/query`
   - Results rendered as cards: each card shows document name, relevance score (displayed as a percentage or star rating), and chunk text
   - No LLM synthesis in this phase — show raw retrieved passages. This is intentional: managers should see exactly what the AI is working from.
   - Empty state: "No relevant sections found. Try rephrasing or uploading more material."
   - Integrate into `KnowledgeBasePage.tsx` as a collapsible panel below the document list

2. **Add AI-synthesized answer endpoint** (optional stretch goal for R7):
   ```
   POST /manager/documents/ask
   Body: {"manager_id": str, "question": str}
   Returns: {"answer": str, "sources": [RetrievedChunk]}
   ```
   - Retrieve top-5 chunks
   - Pass to Claude with prompt: "Answer this question using only the provided company training material. If the material doesn't address the question, say so. Do not invent advice."
   - Return both the synthesized answer and the source chunks so the manager can verify

3. **Tests:**
   - `test_knowledge_base_query_endpoint.py`:
     - Seed 3 chunks with known content
     - POST a query that semantically matches chunk 2
     - Assert chunk 2 is in the top results
   - If AI endpoint is implemented: `test_knowledge_base_ask_endpoint.py` — assert answer references the seeded content and sources list is non-empty
   - `pytest tests/ -x -q` — all tests must pass

---

## Paste-Ready Codex Prompts

### PHASE R1 — Document upload + processing pipeline

```
Bootstrap is loaded. Implement Phase R1 from Daily Workflows/3:7/PRD_RAG_KNOWLEDGE_BASE.md.

Goals:
1. Create OrgDocument and OrgDocumentChunk models in backend/app/models/knowledge.py.
   Alembic migration: enable pgvector extension, create tables, add HNSW index on embedding column.
2. Create DocumentProcessingService in backend/app/services/document_processing_service.py:
   extract_text() dispatching to PDF/DOCX/TXT handlers, chunk_text() with tiktoken token-aware
   chunking (500 tokens, 50 overlap, sentence-boundary-aware), embed_chunks() calling OpenAI
   text-embedding-3-small in batches of 100, process_document() full pipeline.
3. Install: pgvector, pypdf, python-docx, tiktoken.
4. Add POST /manager/documents (multipart upload), GET /manager/documents,
   GET /manager/documents/{id}, DELETE /manager/documents/{id} to backend/app/api/manager.py.
   Processing runs as a FastAPI BackgroundTask.
5. Tests: test_document_upload_and_processing.py (mock OpenAI embeddings call),
   test_document_chunking.py (unit test chunk_text directly).
6. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE R2 — Retrieval service

```
Bootstrap is loaded. Phase R1 is complete. Implement Phase R2 from Daily Workflows/3:7/PRD_RAG_KNOWLEDGE_BASE.md.

Goals:
1. Create DocumentRetrievalService in backend/app/services/document_retrieval_service.py.
   retrieve() runs pgvector cosine similarity query scoped by org_id, returns list[RetrievedChunk].
   retrieve_for_topic() wraps retrieve() with topic + context_hint query construction.
   format_for_prompt() formats chunks as a clean prompt injection block, truncated to max_tokens.
   Cache query embeddings for 15 minutes.
2. Add RetrievedChunk to backend/app/schemas/knowledge.py.
3. Add POST /manager/documents/query endpoint.
4. Tests: test_document_retrieval.py (seed chunks with known vectors, assert correct ranking + org isolation),
   test_retrieval_empty_org.py (assert empty result in < 10ms).
5. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE R3 — Grading injection

```
Bootstrap is loaded. Phase R2 is complete. Implement Phase R3 from Daily Workflows/3:7/PRD_RAG_KNOWLEDGE_BASE.md.

Goals:
1. In GradingService.grade_session(), after loading the active PromptVersion, call
   DocumentRetrievalService().retrieve_for_topic() with org_id, topic about grading rubric
   and methodology, k=4, min_score=0.72. If chunks returned, inject formatted_for_prompt()
   output into the grading prompt before the rubric. If no chunks, grading is unchanged.
2. Look up org_id via the session rep's user record.
3. Tests: test_grading_uses_company_context.py (assert injected section present when chunks exist),
   test_grading_without_documents_unchanged.py (assert no regression for orgs without documents).
4. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE R4 — Homeowner simulation injection

```
Bootstrap is loaded. Phase R3 is complete. Implement Phase R4 from Daily Workflows/3:7/PRD_RAG_KNOWLEDGE_BASE.md.

Goals:
1. In ConversationOrchestrator._build_system_prompt() (or session initialization), call
   DocumentRetrievalService().retrieve_for_topic() with org_id, topic about homeowner objections
   and territory, context_hint from scenario persona and concerns, k=3, min_score=0.70.
   Inject formatted chunks into the homeowner system prompt as a territory/objection context section.
2. Confirm org_id is accessible in the orchestrator — if not, look up via session.rep_id → User.org_id.
3. Tests: test_homeowner_uses_company_objections.py (assert system prompt contains injected context
   when org has relevant documents).
4. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE R5 — Coaching injection

```
Bootstrap is loaded. Phase R4 is complete. Implement Phase R5 from Daily Workflows/3:7/PRD_RAG_KNOWLEDGE_BASE.md.

Goals:
1. In generate_rep_insight(), retrieve company chunks relevant to the rep's weakest skills and
   inject into the Claude prompt so coaching_script references company-specific methodology.
2. In generate_one_on_one_prep(), retrieve chunks relevant to weakest skills and inject into prep prompt.
3. In the manager chat endpoint, retrieve chunks based on classified intent and add to relevant_data
   under key "company_training_context" before calling answer_manager_chat().
4. Tests: test_coaching_uses_company_material.py.
5. Run pytest tests/ -x -q. All tests must pass.
```

### PHASE R6 — Document management UI

```
Bootstrap is loaded. Phase R5 is complete. Implement Phase R6 from Daily Workflows/3:7/PRD_RAG_KNOWLEDGE_BASE.md.

Goals:
1. Create dashboard/src/pages/KnowledgeBasePage.tsx — upload zone, document list with status chips
   (pending/processing amber spinner with 5s auto-refresh, ready green with chunk count, failed red
   with error tooltip), delete with confirm modal, empty state.
2. Create dashboard/src/components/DocumentUploadZone.tsx — drag-and-drop, file type validation,
   upload progress bar, idle/drag-over/uploading/success/error states.
3. Create dashboard/src/lib/knowledge.ts — uploadDocument (with progress), listDocuments,
   deleteDocument, queryDocuments API client functions.
4. Add /knowledge-base route and sidebar navigation link.
5. All components must handle loading, error, and empty states.
```

### PHASE R7 — Direct Q&A interface

```
Bootstrap is loaded. Phase R6 is complete. Implement Phase R7 from Daily Workflows/3:7/PRD_RAG_KNOWLEDGE_BASE.md.

Goals:
1. Create dashboard/src/components/KnowledgeBaseQueryPanel.tsx — search bar, results as cards
   showing document name, similarity score, and chunk text. Raw passages only (no LLM synthesis).
   Integrate as collapsible panel in KnowledgeBasePage.
2. Add POST /manager/documents/ask endpoint — retrieve top-5 chunks, pass to Claude with
   instruction to answer only from provided material, return answer + source chunks.
3. Tests: test_knowledge_base_query_endpoint.py, test_knowledge_base_ask_endpoint.py.
4. Run pytest tests/ -x -q. All tests must pass.
```

---

## Cross-Phase Notes

- **Org ID threading**: Every retrieval call is scoped by `org_id`. Make sure org context is available at each injection point. If a service doesn't currently have org access, look up `User.org_id` from the rep or manager user record — all users have an org_id.
- **Zero regression guarantee**: Every injection point checks `if not chunks: return` before injecting. Orgs without uploaded documents experience zero behavior change.
- **Embedding cost**: A 50-page training manual (~25k tokens) costs ~$0.0005 to embed. Even large orgs uploading a full library won't break the bank.
- **pgvector in tests**: Use SQLite for unit tests where possible. For pgvector-specific tests, mock the similarity query or use a test PostgreSQL instance. Codex should use pre-computed test vectors (hardcoded float arrays) rather than calling OpenAI in tests.
- **R1 is the unlock**: Once R1 is done, all other phases can be developed and tested with pre-seeded chunk data. R2–R5 don't require a real uploaded document in tests.
