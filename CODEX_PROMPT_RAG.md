# Codex Implementation Prompt — Universal RAG Knowledge Base

Read `PRD_Universal_RAG_v1.md` in full before writing any code.

## Context

DoorDrill's AI homeowner currently has no grounding in D2D pest control sales patterns unless an org has uploaded training material. Most orgs have nothing uploaded yet. This means the homeowner persona is operating blind — no knowledge of objection flows, closing techniques, or industry language.

We are adding a **two-layer RAG system**:
- **Universal layer**: a company-agnostic seed knowledge base covering pest control D2D sales, pre-loaded for all orgs
- **Org-specific layer**: existing uploaded training material (already works)

The universal layer seeds from `pest_control_d2d_universal_knowledge.md` (already written, in repo root). Your job is to build the infrastructure to load it, embed it, store it, and retrieve it.

## Implementation Order

Follow exactly the priority order in the PRD:

1. **R-01** — Create `app/models/universal_knowledge.py` with `UniversalKnowledgeChunk` model. Write the Alembic migration.
2. **R-02** — Create `app/services/universal_knowledge_service.py` with `UniversalKnowledgeService`. Wire `parse_seed_document()` and `seed()`.
3. **R-05** — Add `is_universal: bool = False` to `RetrievedChunk` in `app/schemas/knowledge.py`.
4. **R-04** — Update `DocumentRetrievalService` to call `_retrieve_universal_python()` and merge results via `_merge_with_universal()`.
5. **R-06** — Update `format_for_prompt()` to output two labeled blocks: `=== Company Training Material ===` and `=== Industry Sales Knowledge ===`.
6. **R-03** — Add startup seed call to `app/main.py` and admin endpoint `POST /admin/universal-knowledge/seed`.
7. **R-07** — (Optional, last) Add `universal_layer_active` to document upload response.

## Critical Implementation Details

### Model
- Import `EmbeddingVector` from `app.models.knowledge` — do NOT re-declare the type
- `category` field: one of `intro`, `objection_handling`, `reading_homeowner`, `price_framing`, `closing`, `psychology`, `service_value`, `competitor_handling`, `post_pitch`, `backyard_close`
- `source_tag`: `"industry_standard"` for seed content

### Seed Parsing
- The markdown file uses `## [category] Title` for section headers
- Sections are separated by `---` lines
- The parser extracts `[category]` from the heading and the body text below it
- Skip sections where the heading starts with `#` (document header) or content is < 50 chars

### Retrieval Merge Logic (Critical)
- Org-specific chunks **always come first** in the merged result
- Universal chunks **only fill remaining slots** up to `k`
- Universal chunks below `min_score=0.70` are excluded
- If an org-specific chunk already covers a given topic category, the universal chunk for that same category is skipped (avoid redundancy)
- When `org_id` has no documents at all, universal chunks fill all `k` slots

### Format for Prompt
- Org-specific → `=== Company Training Material ===` block
- Universal → `=== Industry Sales Knowledge ===` block
- Universal block only appears if there is token budget remaining after the org-specific block
- If the org has no specific material, only the Industry Knowledge block appears
- Total token budget across both blocks: 1200 tokens (same as current)

### Startup Seed
- Non-fatal: wrap in try/except, log the exception, do NOT re-raise
- Run in a thread pool executor — do NOT block the event loop
- Idempotent: if chunks already exist and `force=False`, log and return 0
- No OpenAI key available (test env): `embed_chunks()` falls back to hash embeddings — chunks still get stored, keyword fallback retrieval still works

## Tests Required

Write tests for:
- `test_universal_knowledge_service.py`:
  - `parse_seed_document()` returns ≥ 15 chunks
  - Each chunk has a valid category
  - `seed()` is idempotent (second call returns 0 without force)
  - `seed(force=True)` replaces existing chunks
- `test_document_retrieval_service.py` (add to existing):
  - Org with no uploaded docs → `retrieve()` returns universal chunks
  - Org with uploaded docs → org-specific chunks appear before universal chunks
  - Universal chunk below `min_score` is excluded from merged result

## Files to Create

- `app/models/universal_knowledge.py`
- `app/services/universal_knowledge_service.py`
- `tests/test_universal_knowledge_service.py`
- Alembic migration for `universal_knowledge_chunks` table

## Files to Modify

- `app/schemas/knowledge.py` — add `is_universal: bool = False` to `RetrievedChunk`
- `app/services/document_retrieval_service.py` — add `_retrieve_universal_python()`, `_merge_with_universal()`, update `retrieve()`, `retrieve_for_topic()`, and `format_for_prompt()`
- `app/main.py` — add startup seed call
- `app/api/routes/admin.py` — add `POST /admin/universal-knowledge/seed` endpoint
- `tests/test_document_retrieval_service.py` — add universal retrieval tests

## What NOT to Change

- `OrgDocument`, `OrgDocumentChunk`, `OrgKnowledgeDoc`, `OrgMaterial` models — no changes
- `CATEGORY_KEYS` in `grading_service.py`
- Existing `retrieve()` function signature or return type
- Existing `format_for_prompt()` public signature (only the implementation changes)
