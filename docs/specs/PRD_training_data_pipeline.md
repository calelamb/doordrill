# PRD: Training Data Pipeline Completeness

**Status:** Ready for implementation
**Scope:** Backend — new model, new service, new admin endpoint, warehouse ETL extension
**Purpose:** Ensure every session generates high-quality (input, output, signal) training pairs for future fine-tuning of a custom homeowner LLM

---

## Background

DoorDrill already has strong infrastructure for grading-side training data:
- `OverrideLabel` captures manager corrections to AI grades with delta scores
- `admin.py /admin/training-signals/export` exports JSONL training pairs: (transcript + prompt_version) → (ai_score + human_correction)
- `GradingRun.prompt_version_id` creates a full audit trail

What's **missing** is the equivalent pipeline for the *conversation* side — the homeowner AI. To fine-tune a custom homeowner LLM, you need:

```
input:  { system_prompt_snapshot, conversation_history_up_to_this_turn }
output: { ai_homeowner_response }
signal: { realism_score, emotion_correctness, human_quality_rating }
```

Currently:
- `SessionTurn` stores what the AI *said* (`text`) and the emotional/behavioral metadata (`mb_*` columns, `emotion_before/after`) — the **output** is captured
- `FactTurnEvent` records `high_realism_turn` / `low_realism_turn` events — a **weak automated signal** exists
- The **system prompt snapshot** per turn is *not* stored anywhere — reconstructable in theory but not persisted
- There is **no human quality signal** for individual AI turns or sessions (separate from rep grading)
- There is **no conversation training export** endpoint

The `document_retrieval_service.py` uses `retrieve_for_topic()` for RAG — the embedding/pgvector infrastructure is assumed to exist (via migrations) but needs to be confirmed wired.

---

## Goals

1. Capture the **system prompt snapshot** for each AI turn (compressed, stored on `SessionTurn`) so training examples have recoverable inputs.
2. Add a **`ConversationQualitySignal`** model for managers to rate AI homeowner realism/difficulty-appropriateness per session.
3. Add a **conversation training export** endpoint that assembles complete (input, output, signal) JSONL examples from completed sessions.
4. Extend the **warehouse ETL** to include conversation quality signal when present.
5. Confirm and complete the **pgvector/embedding pipeline** so RAG is grounded in actual vector similarity rather than falling back silently.

---

## Non-Goals

- Do not build a PyTorch training loop or model inference layer. This is purely data capture and export infrastructure.
- Do not change the grading training signal pipeline (already complete).
- Do not add mobile UI for quality rating (manager-facing only, via existing dashboard API pattern).

---

## Task 1: System Prompt Snapshot on SessionTurn

### 1a. Schema migration

Add one column to `session_turns`:

```sql
ALTER TABLE session_turns ADD COLUMN system_prompt_snapshot TEXT NULL;
```

Alembic migration: create a new revision file in `alembic/versions/`. Column is nullable; old turns will be NULL.

### 1b. ORM model update

In `backend/app/models/session.py`, add to `SessionTurn`:

```python
system_prompt_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### 1c. Write snapshot in ws.py

After `PromptBuilder.build()` returns the system prompt string (and before the LLM call), store a compressed snapshot on the AI turn record:

```python
import zlib, base64

def _compress_prompt(text: str) -> str:
    return base64.b64encode(zlib.compress(text.encode("utf-8"), level=6)).decode("ascii")
```

Write `turn.system_prompt_snapshot = _compress_prompt(system_prompt)` when creating/updating the `SessionTurn` row for the AI speaker.

The compressed form reduces storage by ~70% for typical prompts. The export endpoint will decompress before including in training data.

---

## Task 2: ConversationQualitySignal Model

**File:** `backend/app/models/training.py`

Add a new model:

```python
class ConversationQualitySignal(Base, TimestampMixin):
    __tablename__ = "conversation_quality_signals"
    __table_args__ = (
        Index("ix_conv_quality_signals_session", "session_id"),
        Index("ix_conv_quality_signals_manager_created", "manager_id", "created_at"),
        Index("ix_conv_quality_signals_exported", "exported_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manager_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Overall homeowner realism rating (1-5)
    realism_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Was the homeowner's difficulty level appropriate for the scenario?
    difficulty_appropriate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Did the homeowner respond correctly to the rep's signals?
    signal_responsiveness: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5

    # Free-text notes from the manager (e.g., "homeowner softened too easily on price objection")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Specific turns the manager flagged as low quality
    flagged_turn_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Export tracking
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    export_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
```

Add an Alembic migration for this table.

---

## Task 3: Manager API Endpoint for Quality Signals

**File:** `backend/app/api/manager.py`

Add two endpoints following existing patterns in that file:

### 3a. Submit quality signal

```
POST /manager/sessions/{session_id}/conversation-quality
```

Request body:
```json
{
  "realism_rating": 3,
  "difficulty_appropriate": true,
  "signal_responsiveness": 4,
  "notes": "Homeowner dropped price objection too fast after one acknowledgement.",
  "flagged_turn_ids": ["turn-id-1", "turn-id-2"]
}
```

Upsert (one signal per manager per session). Require `require_manager` auth. Validate that `realism_rating` and `signal_responsiveness` are 1–5 if provided.

### 3b. Get quality signal for session

```
GET /manager/sessions/{session_id}/conversation-quality
```

Returns existing signal or 404 if none submitted.

---

## Task 4: Conversation Training Export Endpoint

**File:** `backend/app/api/admin.py`

Add:

```
GET /admin/training-signals/conversation-export
```

Query params:
- `from_date`, `to_date` (optional date filters)
- `min_realism_score` (float, optional, filters on `SessionTurn.mb_realism_score`)
- `quality_signal_only` (bool, default false — if true, only include sessions with a `ConversationQualitySignal`)
- `format`: `jsonl` (default) or `json`

### Export logic

For each qualifying completed, graded session:

1. Load turns in order.
2. For each AI turn that has a `system_prompt_snapshot`:
   a. Decompress the snapshot.
   b. Build conversation history up to (but not including) this turn: list of `{speaker, text}` dicts.
   c. Load the quality signal for the session (if any).
   d. Emit one JSONL record:

```json
{
  "session_id": "...",
  "turn_id": "...",
  "turn_index": 4,
  "input": {
    "system_prompt": "...(decompressed)...",
    "conversation_history": [
      {"speaker": "rep", "text": "..."},
      {"speaker": "ai", "text": "..."}
    ]
  },
  "output": {
    "text": "...",
    "emotion_before": "neutral",
    "emotion_after": "skeptical",
    "stage": "objection_handling"
  },
  "signals": {
    "mb_realism_score": 8.2,
    "mb_tone": "guarded",
    "mb_behaviors": ["tone_hardening", "objection_aware"],
    "was_graded": true,
    "is_high_quality": true,
    "manager_realism_rating": 4,
    "manager_flagged": false
  },
  "metadata": {
    "scenario_id": "...",
    "scenario_name": "Price Hawk",
    "scenario_difficulty": 2,
    "prompt_version": "conversation_v1",
    "org_id": "...",
    "session_date": "2026-03-01"
  }
}
```

Mark exported turns/sessions (set `ConversationQualitySignal.exported_at` if present). Do NOT mark individual turns — the export is always re-runnable by date range.

---

## Task 5: Confirm and Complete pgvector Embedding Pipeline

**File:** `backend/app/services/document_retrieval_service.py`

Read the current implementation of `retrieve_for_topic()`. Confirm whether it:

a. Actually calls an embedding API (OpenAI embeddings or equivalent) to get a query vector
b. Uses pgvector `<=>` or `<->` operator for similarity search
c. Falls back gracefully to keyword search if pgvector is not available

If the embedding call is stubbed, missing, or falls back silently:

1. Add a `_embed_query(text: str) -> list[float]` method that calls `openai.embeddings.create(model="text-embedding-3-small", input=text)` using the existing `settings.openai_api_key`.

2. Update `retrieve_for_topic()` to use the embedding when available, with a graceful fallback to ILIKE keyword search if embedding fails or if pgvector is not installed.

3. Add `text-embedding-3-small` as the default embedding model to `config.py` settings:
   ```python
   embedding_model: str = Field(default="text-embedding-3-small")
   ```

**Also:** Ensure `OrgDocument` chunks store their embeddings. Check `document_processing_service.py`. If `chunk.embedding` is not being written (only text is stored), add the embedding write step in the chunking pipeline:

```python
embedding = await self._embed_text(chunk_text)
chunk.embedding = embedding  # stored as pgvector column
```

This ensures future document uploads produce searchable embeddings immediately.

---

## Task 6: Warehouse ETL Extension

**File:** `backend/app/services/warehouse_etl_service.py`

In `_upsert_fact_session()`, add:

```python
"has_conversation_quality_signal": bool(...),
"conversation_realism_rating": ...,   # int or None
"conversation_signal_responsiveness": ...,  # int or None
```

Query `ConversationQualitySignal` in `_load_session_with_relations()` and include in the bundle.

Add the corresponding columns to `FactSession` model in `backend/app/models/warehouse.py` (nullable).

Add Alembic migration for these columns.

---

## Task 7: Tests

**File:** `backend/tests/test_training_data_pipeline.py`

Test:

1. System prompt snapshot is written to `SessionTurn.system_prompt_snapshot` during a WS session (mock LLM, use existing WS test patterns).

2. `_compress_prompt()` and its inverse are lossless (round-trip test).

3. `POST /manager/sessions/{id}/conversation-quality` creates a signal; second call upserts.

4. `GET /admin/training-signals/conversation-export` returns JSONL with correct shape — one record per AI turn that has a snapshot.

5. Export with `quality_signal_only=true` excludes sessions without a quality signal.

6. `retrieve_for_topic()` returns results when pgvector is available; falls back without crashing when it's not.

---

## Acceptance Criteria

- [ ] `SessionTurn.system_prompt_snapshot` is populated for every AI turn in a session
- [ ] `ConversationQualitySignal` table and manager endpoints work correctly
- [ ] `/admin/training-signals/conversation-export` produces valid JSONL with (input, output, signals) per AI turn
- [ ] Export records include decompressed system prompt
- [ ] pgvector embedding is wired; `retrieve_for_topic()` uses real vectors when available
- [ ] Document processing pipeline writes embeddings on ingest
- [ ] Warehouse ETL includes quality signal fields
- [ ] All Alembic migrations generate cleanly
- [ ] All tests pass

---

## Reference Files

- `backend/app/models/training.py` — `OverrideLabel` is the model pattern to follow for `ConversationQualitySignal`
- `backend/app/api/admin.py` — `/admin/training-signals/export` is the exact export pattern to mirror
- `backend/app/services/warehouse_etl_service.py` — `_load_session_with_relations()` and `_upsert_fact_session()` patterns
- `backend/app/services/document_retrieval_service.py` — current RAG retrieval to audit and complete
- `backend/app/services/document_processing_service.py` — chunking pipeline to audit for missing embedding write
- `backend/app/voice/ws.py` — where `PromptBuilder.build()` is called and where AI turns are committed
