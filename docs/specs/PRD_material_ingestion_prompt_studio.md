# PRD: Material Ingestion, Questionnaire & Prompt Studio

**Status:** Ready for implementation
**Scope:** Backend — ingestion pipeline, extraction service, questionnaire system, Prompt Studio API
**Depends on:** PRD: Multi-Tenant Org Config & Prompt Isolation (must be complete first)

---

## Background

Managers need a way to configure DoorDrill for their specific company without writing prompts. This PRD delivers the full onboarding flow:

1. **Upload materials** — training videos, sales manuals, pricing sheets, competitor comparisons, objection guides
2. **Automatic extraction** — an LLM-powered pipeline extracts structured knowledge (objections, rebuttals, USPs, competitors, pricing framing) from every uploaded file
3. **Guided questionnaire** — a fixed set of multiple-choice and short-answer questions fills in what materials can't capture (tone philosophy, close style, rep culture)
4. **Prompt Studio review** — the system drafts every prompt layer from the extracted data + questionnaire answers; the manager reviews, edits, and publishes

When published, the `OrgPromptConfig` is live and all rep sessions for that org use the company-specific prompt configuration.

---

## Non-Goals

- No frontend UI in this PRD — API endpoints only. The frontend team consumes these.
- No fine-tuning or model training in this PRD — that is a future milestone.
- No video generation or synthetic rep content.
- No real-time streaming of extraction progress (polling endpoint is sufficient for v1).

---

## Part 1: Material Upload & Storage

### Model: `OrgMaterial`

**File:** `backend/app/models/org_material.py` (new)

```python
class OrgMaterial(Base):
    __tablename__ = "org_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)
    # "pdf" | "video" | "audio" | "docx" | "txt" | "csv"

    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    # S3 key or local path. Upload handled by existing file storage layer.

    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=True)

    # Extraction state
    extraction_status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    # "pending" | "transcribing" | "extracting" | "complete" | "failed"

    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full plain text after transcription/parsing, before LLM extraction

    extracted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    knowledge_docs: Mapped[list["OrgKnowledgeDoc"]] = relationship(back_populates="material")
```

### Model: `OrgKnowledgeDoc`

**File:** `backend/app/models/org_material.py` (same file, second model)

Each extracted fact from a material file becomes one `OrgKnowledgeDoc`. This is the structured output of the extraction pass.

```python
class OrgKnowledgeDoc(Base):
    __tablename__ = "org_knowledge_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("org_materials.id"), nullable=False)

    extraction_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # "objection" | "rebuttal" | "usp" | "competitor" | "pricing" | "persona_insight"
    # | "pitch_technique" | "company_fact"

    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The extracted fact in plain English

    supporting_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The source text from the material that led to this extraction (for manager review)

    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # LLM's self-reported confidence: 0.0–1.0
    # Low confidence items are flagged for manager review in Prompt Studio

    manager_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # None = not reviewed, True = approved, False = rejected
    # Only approved docs are used in OrgPromptConfig synthesis

    used_in_config: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set True when this doc is incorporated into the published OrgPromptConfig

    # pgvector embedding for RAG retrieval during sessions
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    material: Mapped["OrgMaterial"] = relationship(back_populates="knowledge_docs")
```

### API: Upload Endpoint

```
POST /admin/orgs/{org_id}/materials
     Multipart form upload. Accepts: pdf, mp4, mp3, m4a, docx, txt, csv.
     Creates OrgMaterial record with status="pending".
     Enqueues MaterialExtractionTask via Celery (or asyncio background task).
     Returns: { material_id, extraction_status: "pending" }

GET  /admin/orgs/{org_id}/materials
     Lists all materials for the org with their extraction_status.

GET  /admin/orgs/{org_id}/materials/{material_id}/status
     Polls extraction progress. Returns extraction_status, extracted doc count,
     any extraction_error.

DELETE /admin/orgs/{org_id}/materials/{material_id}
     Soft-delete (set a deleted_at timestamp). Does not remove from storage.
```

---

## Part 2: Extraction Pipeline

### Service: `MaterialExtractionService`

**File:** `backend/app/services/material_extraction_service.py` (new)

This is the core pipeline. It runs as a background task after each upload.

```python
class MaterialExtractionService:

    async def process(self, material_id: int, db: Session) -> None:
        """
        Full pipeline for one uploaded material:
        1. transcribe_or_parse()  — convert to plain text
        2. chunk_and_embed()      — split into RAG chunks, embed, store in pgvector
        3. extract_structured()   — LLM extraction pass → OrgKnowledgeDoc records
        """

    async def transcribe_or_parse(self, material: OrgMaterial) -> str:
        """
        Dispatches based on file_type:
        - pdf/docx/txt/csv: parse to plain text using existing document parsing utilities
        - video (mp4): extract audio stream → send to Deepgram transcription API (reuse
          existing Deepgram client from voice pipeline, batch mode not streaming)
        - audio (mp3/m4a): send directly to Deepgram transcription API

        Stores result in material.raw_transcript.
        Updates material.extraction_status = "transcribing" → "extracting".
        """

    async def chunk_and_embed(self, material: OrgMaterial, raw_text: str) -> None:
        """
        Splits raw_text into chunks (800 tokens, 100 token overlap).
        Embeds each chunk using the existing embedding model (from document_retrieval_service).
        Stores chunks as OrgKnowledgeDoc records with extraction_type="raw_chunk" and
        embedding set, manager_approved=True (raw chunks don't need review — they feed RAG).
        Scopes all chunks to org_id so session RAG only searches this org's docs.
        """

    async def extract_structured(self, material: OrgMaterial, raw_text: str) -> list[OrgKnowledgeDoc]:
        """
        Single LLM call (Claude 3.5 Sonnet) with the full raw_text.
        Prompt instructs the model to extract ALL of the following in one pass:
        - objections (customer concerns mentioned or implied)
        - rebuttals (responses to objections, from rep perspective)
        - unique selling points (features/benefits highlighted)
        - competitors (names + differentiators mentioned)
        - pricing signals (framing language, not specific numbers)
        - persona insights (homeowner types, demographics, scenarios described)
        - pitch techniques (specific techniques or frameworks described)
        - company facts (mission, history, certifications, awards)

        Response is structured JSON (use Claude tool_use / structured output).
        Each item becomes one OrgKnowledgeDoc.
        Confidence is derived from how explicitly the fact appeared in the source
        vs. how much it was inferred (ask model to self-report in JSON output).

        Updates material.extraction_status = "complete" on success, "failed" on error.
        """
```

### Extraction Prompt Template

**File:** `backend/app/prompt_templates/material_extraction.j2`

The extraction prompt uses Claude's tool_use feature to guarantee structured output. Define a tool schema with the following structure:

```json
{
  "name": "record_extracted_knowledge",
  "description": "Record all structured knowledge extracted from this sales training material.",
  "input_schema": {
    "type": "object",
    "properties": {
      "objections": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "content": {"type": "string"},
            "supporting_quote": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
          }
        }
      },
      "rebuttals": { "...same structure..." },
      "unique_selling_points": { "...same structure..." },
      "competitors": { "...same structure..." },
      "pricing_signals": { "...same structure..." },
      "persona_insights": { "...same structure..." },
      "pitch_techniques": { "...same structure..." },
      "company_facts": { "...same structure..." }
    }
  }
}
```

System prompt for extraction:
```
You are a sales training analyst. Analyze the provided material and extract every piece
of knowledge that would help train a door-to-door sales rep. Be thorough — extract every
objection mentioned (even implicitly), every rebuttal or response technique, every
product benefit, and every competitor reference.

For each extracted item:
- content: the fact in one clear sentence
- supporting_quote: the exact text from the source that led you to this extraction
- confidence: 1.0 if explicitly stated, 0.7 if clearly implied, 0.4 if inferred
```

---

## Part 3: Questionnaire System

### Model: `QuestionnaireQuestion`

**File:** `backend/app/models/questionnaire.py` (new)

The question bank is seeded by us (DoorDrill). Questions are never written by managers; they only answer them.

```python
class QuestionnaireQuestion(Base):
    __tablename__ = "questionnaire_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # Machine-readable key used to map answer to OrgPromptConfig field
    # e.g. "close_style", "product_category", "target_age_range"

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # What the manager sees: "How would you describe your reps' closing style?"

    question_type: Mapped[str] = mapped_column(String, nullable=False)
    # "single_choice" | "multi_choice" | "short_text" | "long_text"

    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # For choice questions: [{"value": "consultative", "label": "Consultative — build trust first"},
    #                         {"value": "assumptive", "label": "Assumptive — move toward yes"},
    #                         {"value": "urgency", "label": "Urgency-based — limited time offer"}]

    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # Controls ordering in the manager UI

    category: Mapped[str] = mapped_column(String, nullable=False)
    # "product" | "pitch" | "persona" | "culture" | "competitive"
    # Groups questions into logical sections in the UI

    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    maps_to_config_field: Mapped[str | None] = mapped_column(String, nullable=True)
    # If set, answer is written directly to this OrgPromptConfig field.
    # e.g. "close_style" → writes answer value to org_prompt_configs.close_style
    # If null, answer is stored in OrgQuestionnaireResponse and used by
    # the PromptStudioService to assemble the config.

    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

### Model: `OrgQuestionnaireResponse`

```python
class OrgQuestionnaireResponse(Base):
    __tablename__ = "org_questionnaire_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questionnaire_questions.id"), nullable=False)
    answer_value: Mapped[str] = mapped_column(Text, nullable=False)
    # Serialized answer. For multi_choice, JSON array as string.
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "question_id", name="uq_org_questionnaire_response"),
    )
```

### Question Bank Seed Data

**File:** `backend/app/db/seed_questionnaire.py` (new, called from `init_db.py`)

Seed the following questions (this is v1 — can be expanded over time):

**Category: product**
- `product_category` (single_choice): "What does your company sell?" → options: Residential Solar, Home Security, Pest Control, Fiber Internet, HVAC, Other
- `product_description` (long_text): "In 2–3 sentences, describe what you sell and the core value to homeowners."
- `pricing_framing` (long_text): "How should reps describe pricing on the door? (e.g., 'never quote numbers until site survey', 'lead with monthly savings')"

**Category: pitch**
- `close_style` (single_choice): "How would you describe your reps' closing approach?" → options: Consultative (build trust, let homeowner decide), Assumptive (confidently move toward yes), Urgency-based (limited offer / time pressure)
- `pitch_stages` (multi_choice): "Which stages does your pitch typically include?" → options: Door approach, Initial value pitch, Objection handling, Consideration pause, Close attempt, Follow-up scheduling
- `key_objections` (long_text): "List the 3–5 most common objections your reps face and how they should respond."

**Category: persona**
- `target_age_range` (single_choice): "What age range are you typically targeting?" → options: 25–40, 35–55, 45–65, 55+, Mixed
- `target_homeowner_type` (single_choice): "Describe your typical homeowner." → options: Suburban family homeowner, Rural property owner, Urban condo/townhome owner, Mixed
- `common_homeowner_concerns` (multi_choice): "What are the most common homeowner concerns?" → options: Cost / monthly payment, Installation disruption, HOA restrictions, Product reliability, Sales rep trustworthiness, Contract length

**Category: culture**
- `rep_tone_guidance` (single_choice): "What tone should your reps project?" → options: Professional and warm, Casual and friendly, Technical expert, High energy and enthusiastic
- `grading_priorities` (multi_choice, ordered): "Rank what matters most when grading a rep's performance." → options: Rapport building, Objection handling, Value prop clarity, Close attempt, Professionalism, Listening skills

**Category: competitive**
- `main_competitors` (long_text): "Who are your main competitors and what's your key differentiator against each?"

### Questionnaire API

```
GET  /admin/orgs/{org_id}/questionnaire
     Returns all active questions with current answers for this org (if any).
     Groups by category. Shows completion percentage.

POST /admin/orgs/{org_id}/questionnaire/answers
     Body: [{ question_key, answer_value }, ...]
     Upserts answers. For questions with maps_to_config_field, immediately
     writes value to the OrgPromptConfig draft.
     Returns updated completion status.

GET  /admin/orgs/{org_id}/questionnaire/completion
     Returns { total_questions, answered, required_unanswered: [...] }
     Frontend uses this to gate the "Generate Draft" button.
```

---

## Part 4: Prompt Studio Service & API

### Service: `PromptStudioService`

**File:** `backend/app/services/prompt_studio_service.py` (new)

This service is the brain of the Prompt Studio. It combines extracted knowledge + questionnaire answers to produce a draft `OrgPromptConfig`.

```python
class PromptStudioService:

    def generate_draft_config(self, org_id: str, db: Session) -> OrgPromptConfig:
        """
        Called when manager clicks "Generate Draft" after uploading materials
        and completing the questionnaire.

        Steps:
        1. Load all OrgQuestionnaireResponse for this org.
        2. Load all OrgKnowledgeDoc for this org (extraction_type != "raw_chunk").
        3. Merge: questionnaire answers take precedence over extracted values.
           Extracted values fill in gaps the questionnaire didn't cover.
        4. Write merged result to OrgPromptConfig fields (creates or updates draft).
        5. For fields that need synthesis (e.g. combining 5 extracted objections into
           the known_objections JSON structure), run _synthesize_field().
        6. Returns draft config with published=False.
        """

    def _synthesize_field(
        self,
        field_name: str,
        extracted_docs: list[OrgKnowledgeDoc],
        questionnaire_answer: str | None,
    ) -> Any:
        """
        For complex fields (known_objections, unique_selling_points, competitors):
        - Deduplicates extracted items (multiple docs may say the same thing differently)
        - Merges with questionnaire free-text answers
        - Returns structured value ready for OrgPromptConfig JSON field

        For known_objections specifically:
        - Groups extracted "objection" docs with their paired "rebuttal" docs
        - Produces: [{"objection": "...", "preferred_rebuttal_hint": "..."}]
        """

    def get_draft_preview(self, org_id: str, db: Session) -> dict:
        """
        Returns a human-readable preview of what the generated prompts will look like.
        Does NOT write to DB.

        Returns:
        {
          "layer_0_preview": "...",      # Company context layer
          "conversation_prompt": "...",   # Full synthesized conversation prompt
          "grading_prompt": "...",        # Full synthesized grading prompt
          "coaching_prompt": "...",       # Full synthesized coaching prompt
          "system_prompt_token_count": 847,
          "knowledge_docs_used": 23,
          "low_confidence_items": [...]   # Items manager should review
        }
        """

    def get_knowledge_docs_for_review(self, org_id: str, db: Session) -> list[OrgKnowledgeDoc]:
        """
        Returns all OrgKnowledgeDocs with manager_approved=None (not yet reviewed).
        Sorted: low confidence first.
        Used by Prompt Studio review UI to show manager what was extracted.
        """

    def approve_knowledge_doc(self, doc_id: int, approved: bool, db: Session) -> None:
        """Sets manager_approved on a single doc."""

    def update_draft_field(self, org_id: str, field: str, value: Any, db: Session) -> OrgPromptConfig:
        """
        Direct field edit from Prompt Studio UI.
        Manager can edit any field of the draft config.
        Validates field name against OrgPromptConfig columns.
        """
```

### Prompt Studio API Endpoints

```
POST /admin/orgs/{org_id}/prompt-studio/generate
     Triggers PromptStudioService.generate_draft_config().
     Returns the full draft OrgPromptConfig.
     Prerequisite: at least one material extracted + questionnaire completion > 80%.
     Returns 400 with list of missing requirements if prerequisites not met.

GET  /admin/orgs/{org_id}/prompt-studio/preview
     Returns PromptStudioService.get_draft_preview().
     No DB writes. Safe to call repeatedly.

GET  /admin/orgs/{org_id}/prompt-studio/knowledge-docs
     Returns all extracted knowledge docs grouped by extraction_type.
     Includes manager_approved status and confidence score.
     Query params: ?approved=null|true|false, ?type=objection|rebuttal|...

PATCH /admin/orgs/{org_id}/prompt-studio/knowledge-docs/{doc_id}
      Body: { "approved": true|false }
      Approves or rejects a single extracted knowledge item.

PATCH /admin/orgs/{org_id}/prompt-studio/config
      Body: any subset of OrgPromptConfig fields
      Direct field edits by manager in Prompt Studio.
      Returns updated draft config.

POST /admin/orgs/{org_id}/prompt-studio/regenerate
     Re-runs generate_draft_config() after manager has approved/rejected docs
     or edited questionnaire answers. Overwrites draft (published stays False).

POST /admin/orgs/{org_id}/prompt-studio/publish
     Calls OrgPromptConfigService.publish_config() (from PRD 1).
     This triggers PromptVersionSynthesizer → generates PromptVersion records.
     Returns { published_at, prompt_versions: {...}, system_prompt_token_count }
```

---

## Part 5: Session-Time RAG — Org-Scoped Retrieval

The existing RAG system retrieves pricing and competitor chunks at session start. Now that chunks are tagged with `org_id`, the retrieval must be scoped.

**File:** `backend/app/services/document_retrieval_service.py`

Update all retrieval functions to accept and filter by `org_id`:

```python
def retrieve_for_topic(
    topic: str,
    org_id: str,
    k: int = 3,
    db: Session = ...,
) -> list[str]:
    """
    Vector similarity search scoped to org_id.
    Searches OrgKnowledgeDoc embeddings (extraction_type != "raw_chunk" filtered out
    unless specifically requested, since raw chunks are for full-text RAG not topic retrieval).
    Falls back to global documents (org_id IS NULL) if org has no matching chunks.
    """
```

Update `ws.py` session-start RAG calls to pass `session.org_id` to both retrieval functions. This is a small change — add `org_id=session.org_id` to each call.

---

## Part 6: Database Migration

**File:** `backend/alembic/versions/XXXX_material_ingestion_questionnaire.py`

- Create `org_materials` table
- Create `org_knowledge_docs` table with pgvector `embedding` column (1536 dimensions)
- Create `questionnaire_questions` table
- Create `org_questionnaire_responses` table
- Add index on `org_knowledge_docs(org_id, extraction_type, manager_approved)`
- Add index on `org_knowledge_docs(org_id)` for RAG retrieval filter

Run seed for questionnaire questions via `seed_questionnaire.py` as part of migration.

---

## Part 7: Celery Task

**File:** `backend/app/tasks/material_tasks.py` (new or add to existing tasks file)

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_material(self, material_id: int) -> None:
    """
    Celery task that wraps MaterialExtractionService.process().
    Called immediately after OrgMaterial record is created.
    Updates extraction_status throughout.
    On failure: sets extraction_status="failed", stores error message,
    retries up to 3 times with 30s delay.
    """
```

If Celery is not available (dev environment), fall back to `asyncio.create_task()` as a background coroutine.

---

## Onboarding Flow Summary

For clarity, the full manager onboarding sequence is:

```
1. Manager navigates to Prompt Studio in the dashboard
2. Uploads one or more files → POST /admin/orgs/{org_id}/materials (repeat per file)
3. Polls extraction status → GET /admin/orgs/{org_id}/materials/{id}/status
4. Answers questionnaire → POST /admin/orgs/{org_id}/questionnaire/answers
5. Clicks "Generate Draft" → POST /admin/orgs/{org_id}/prompt-studio/generate
6. Reviews extracted knowledge docs, approves/rejects → PATCH .../knowledge-docs/{id}
7. Previews generated prompts → GET /admin/orgs/{org_id}/prompt-studio/preview
8. Edits any field directly → PATCH /admin/orgs/{org_id}/prompt-studio/config
9. Optionally regenerates after edits → POST /admin/orgs/{org_id}/prompt-studio/regenerate
10. Publishes → POST /admin/orgs/{org_id}/prompt-studio/publish
    → PromptVersion records generated and activated for org
    → Rep sessions now use org-specific prompts
```

---

## Acceptance Criteria

- [ ] `org_materials`, `org_knowledge_docs`, `questionnaire_questions`, `org_questionnaire_responses` tables created via migration
- [ ] PDF/DOCX/TXT files parse to plain text and produce `OrgKnowledgeDoc` records
- [ ] Video/audio files transcribe via Deepgram batch API and produce `OrgKnowledgeDoc` records
- [ ] LLM extraction pass produces structured docs for all 8 extraction types
- [ ] `supporting_quote` and `confidence` populated on each extracted doc
- [ ] Questionnaire seed data present for all 12 questions across 5 categories
- [ ] `POST /questionnaire/answers` writes directly to `OrgPromptConfig` for mapped fields
- [ ] `generate_draft_config()` merges questionnaire + extracted docs into coherent `OrgPromptConfig`
- [ ] Duplicate/near-duplicate extracted items are collapsed, not doubled
- [ ] `get_draft_preview()` returns rendered prompt text for all 3 prompt types without DB writes
- [ ] `publish` endpoint triggers `PromptVersionSynthesizer` and activates org-specific PromptVersions
- [ ] Session-time RAG retrieval is scoped to `org_id` with global fallback
- [ ] Celery task retries on failure; `extraction_status` reflects actual state at all times
- [ ] System prompt token count stays under hard limit (1600 tokens) after org config is injected

---

## Reference Files

- `backend/app/models/` (new: `org_material.py`, `questionnaire.py`)
- `backend/app/services/material_extraction_service.py` (new)
- `backend/app/services/prompt_studio_service.py` (new)
- `backend/app/services/org_prompt_config_service.py` (from PRD 1)
- `backend/app/services/prompt_version_synthesizer.py` (from PRD 1)
- `backend/app/services/document_retrieval_service.py` (update org_id scoping)
- `backend/app/api/admin.py` (add all new endpoints)
- `backend/app/tasks/material_tasks.py` (new Celery task)
- `backend/app/prompt_templates/material_extraction.j2` (new)
- `backend/app/db/seed_questionnaire.py` (new)
- `backend/alembic/versions/` (new migration)
