# PRD: Transcript Pipeline
## First-Class Structured Storage of Every Turn, Emotion, Objection, and Micro-Behavior

**Owner:** Engineering
**Status:** Ready for implementation
**Depended on by:** Grading Engine V2 (evidence linking), Data Warehouse Layer (warehouse quality), Training Loop (fine-tuning corpus)

---

## Problem Statement

The DoorDrill conversation system produces remarkably rich data during every session. The emotion state machine, micro-behavior engine, objection tags, barge-in events, and stage transitions all fire in real time. But almost none of this richness survives as queryable, structured data:

- `session_turns` stores `objection_tags` as a JSON array column — no FK to an objection taxonomy, no severity score, no whether the objection was resolved or not.
- Emotion states live inside `session_events.payload` as JSON blobs — `{"emotion": "skeptical", "stage": "door_knock"}`. There's no `turn_emotion_transitions` table. You cannot query "how many reps successfully de-escalated from hostile to interested in the close_attempt stage this month" without full-table JSON scanning.
- Micro-behavior data (`tone`, `sentence_length`, `realism_score`, `pause_profile`) was recently wired into the WebSocket path and stored on `server.turn.committed` event payloads — again as JSON inside `session_events`. There's no `fact_turn_micro_behaviors` table.
- The conversation orchestrator's full state snapshot (objection pressure, resistance level, active vs. queued objections) is not persisted per turn at all — it lives in memory and disappears when the session closes.

For fine-tuning, you need to answer questions like:
- "Show me all turns where the rep said something that reduced objection pressure from 4 to 2 while in the skeptical emotional state" — this is a training slice.
- "What are the 50 highest-realism turns across all sessions this month?" — this is a quality signal.
- "Which reps consistently produce hostile-emotion endings vs. curious-emotion endings?" — this is a coaching signal.

None of these queries are possible today without expensive JSON scanning.

---

## Goals

1. Upgrade `session_turns` to store emotion state, micro-behavior, and orchestrator state as typed columns — not JSON blobs.
2. Create `fact_turn_events` — one row per meaningful event in a session (emotion transition, objection surfaced/resolved, barge-in, stage change) as first-class records.
3. Add `objection_taxonomy` — a versioned, org-scoped catalog of objection types with metadata.
4. Make every turn fully self-contained for training export: you should be able to reconstruct a training example from a single `session_turns` row join.
5. Keep backward compatibility — existing `session_events` immutable log stays intact. The new tables are derived/enriched, not replacements.

---

## Non-Goals

- This PRD does NOT store audio waveform data or embeddings — that's a future vector store PRD.
- This PRD does NOT remove or modify `session_events` — the immutable event ledger stays unchanged.
- This PRD does NOT change the WebSocket protocol — turn enrichment happens in the postprocess pipeline, not during the live session.

---

## Architecture

### 1. Enriched `session_turns` — New Columns

Add columns to the existing `session_turns` table via migration. These are nullable so existing rows are unaffected.

```sql
-- Emotion context at the time this turn was spoken
emotion_before       VARCHAR(32)  -- emotion when this turn started
emotion_after        VARCHAR(32)  -- emotion at end of this turn
emotion_changed      BOOLEAN      DEFAULT false
resistance_level     SMALLINT     -- 1–5

-- Orchestrator state snapshot
objection_pressure   SMALLINT     -- 0–5
active_objections    JSONB        -- list of objection tags currently "live"
queued_objections    JSONB        -- list of objection tags queued but not yet surfaced
stage                VARCHAR(64)  -- already exists, but currently nullable — make NOT NULL with migration

-- Micro-behavior (from ConversationalMicroBehaviorEngine)
mb_tone              VARCHAR(32)  -- e.g. "guarded", "sharp", "exploratory"
mb_sentence_length   VARCHAR(16)  -- "short", "medium", "long"
mb_behaviors         JSONB        -- list: ["tone_shift", "hesitation_filler"]
mb_interruption_type VARCHAR(32)  -- "barge_in" | "preemptive" | null
mb_realism_score     FLOAT        -- 0.0–10.0
mb_opening_pause_ms  INT
mb_total_pause_ms    INT

-- Behavioral signal classification (for training)
behavioral_signals   JSONB        -- list: ["acknowledged_objection", "price_anchor", "explains_value"]
-- derived by the postprocess pipeline from turn text + context

-- Training metadata
was_graded           BOOLEAN      DEFAULT false   -- did a GradingRun reference this turn?
evidence_for_categories JSONB     -- list of category keys this turn was evidence for
is_high_quality      BOOLEAN      DEFAULT null    -- set by override label alignment check
```

**Migration strategy:** All new columns are nullable or have defaults — zero-downtime deploy. A backfill Celery task re-processes sessions to populate these columns from `session_events.payload`.

---

### 2. New Table: `fact_turn_events`

One row per discrete event that happens within a turn. More granular than `session_turns` — designed for training slice queries.

```python
class FactTurnEvent(Base, TimestampMixin):
    __tablename__ = "fact_turn_events"
    __table_args__ = (
        Index("ix_fact_turn_events_session", "session_id"),
        Index("ix_fact_turn_events_rep_event_type", "rep_id", "event_type"),
        Index("ix_fact_turn_events_org_event_type_created", "org_id", "event_type", "created_at"),
    )

    id: str                  # uuid
    session_id: str          # FK sessions.id
    turn_id: str | None      # FK session_turns.id (null for session-level events)
    rep_id: str              # FK users.id
    org_id: str              # FK organizations.id
    event_type: str          # see EVENT_TYPES below
    occurred_at: datetime

    # Event payload — typed per event_type
    emotion_before: str | None
    emotion_after: str | None
    objection_tag: str | None
    objection_resolved: bool | None
    stage_before: str | None
    stage_after: str | None
    resistance_delta: int | None   # positive = got harder, negative = got easier
    pressure_delta: int | None
    mb_realism_score: float | None
    signal_tags: list[str]         # behavioral signals active at this event
    context_json: dict             # catch-all for event-specific metadata
```

**EVENT_TYPES:**
```
"emotion_transition"      — emotion changed between turns
"objection_surfaced"      — new objection entered active_objections
"objection_resolved"      — objection removed from active_objections
"stage_advance"           — conversation moved to next stage
"stage_stall"             — rep remained in same stage after expected advance
"barge_in"                — rep interrupted AI mid-response
"resistance_spike"        — resistance_level increased by 2+
"resistance_drop"         — resistance_level decreased (rep is winning)
"session_ended_hostile"   — session closed while emotion == "hostile"
"session_ended_interested"— session closed while emotion in {"interested", "curious"}
"high_realism_turn"       — mb_realism_score >= 8.0
"low_realism_turn"        — mb_realism_score <= 3.0
```

This table is the primary index for training slice queries. "Show me all resistance_drop events in close_attempt stage where overall_score >= 7" becomes a simple indexed query.

---

### 3. Objection Taxonomy

Today objection tags are free-form strings in `session_turns.objection_tags` JSON arrays — `["price", "incumbent_provider", "timing"]`. There's no canonical list, no severity ranking, no grouping.

**New model: `ObjectionType`**:

```python
class ObjectionType(Base, TimestampMixin):
    __tablename__ = "objection_types"
    __table_args__ = (
        UniqueConstraint("org_id", "tag", name="uq_objection_type_org_tag"),
    )

    id: str
    org_id: str | None      # null = system-level, non-null = org-specific override
    tag: str                # e.g. "price", "incumbent_provider", "timing"
    display_name: str       # e.g. "Price Objection", "Already Has a Provider"
    category: str           # "price" | "trust" | "timing" | "incumbent" | "need" | "spouse"
    difficulty_weight: float  # 0.0–1.0 — how much this objection increases session difficulty
    industry: str | None    # "pest_control" | null = all industries
    typical_phrases: list[str]  # example phrases that signal this objection
    resolution_techniques: list[str]  # recommended techniques for managers to coach
    version: str            # "1.0" — for taxonomy evolution tracking
    active: bool
```

**Seed data:** Add a migration that inserts the canonical D2D pest control objection taxonomy:
- price, price_per_month, price_vs_competitor
- incumbent_provider, locked_in_contract
- timing, not_right_now, busy
- trust, skeptical_of_product, skeptical_of_rep
- need, no_pest_problem
- decision_authority (need spouse/landlord approval)

---

### 4. Turn Enrichment Pipeline

New service: `TurnEnrichmentService` — runs as part of `SessionPostprocessService` after grading.

```python
class TurnEnrichmentService:
    """
    Re-processes session_events to populate enriched columns on session_turns
    and write fact_turn_events rows.
    Called once per session after grading completes.
    Idempotent — safe to re-run.
    """

    def enrich_session(self, db: Session, session_id: str) -> None:
        events = self._load_ordered_events(db, session_id)
        turns = self._load_turns(db, session_id)
        turn_map = {t.id: t for t in turns}

        # Reconstruct orchestrator state timeline from session_events
        timeline = self._reconstruct_state_timeline(events)

        # Enrich turns with context from timeline
        for turn in turns:
            state_at_turn = timeline.get_state_at(turn.started_at)
            self._enrich_turn(db, turn, state_at_turn)

        # Write fact_turn_events
        self._write_fact_turn_events(db, session_id, timeline, turns)

        db.commit()

    def _reconstruct_state_timeline(self, events: list) -> StateTimeline:
        """
        Replay session_events in order to reconstruct the orchestrator state
        at each point in time. Returns a StateTimeline object queryable by timestamp.
        """
```

The timeline reconstruction reads `session_events` rows — specifically:
- `server.session.state` → session-level state snapshots (emotion, stage, resistance)
- `server.turn.committed` → turn-level state with micro_behavior payload
- Any event with `emotion`, `stage`, `objection_pressure` in payload

---

### 5. Training Export Integration

The Transcript Pipeline directly enables better training exports. Update `GET /admin/training-signals/export` (from Training Loop PRD) to include per-turn structure:

```json
{
  "input": {
    "session_id": "...",
    "scenario": {"name": "...", "difficulty": 3},
    "turns": [
      {
        "turn_index": 1,
        "speaker": "rep",
        "text": "Hi, I'm with Acme Pest...",
        "stage": "door_knock",
        "emotion_before": "skeptical",
        "emotion_after": "skeptical",
        "objection_pressure": 3,
        "active_objections": ["price"],
        "mb_realism_score": 7.2,
        "behavioral_signals": ["rapport_attempt"],
        "evidence_for_categories": []
      }
    ],
    "key_events": [
      {"event_type": "resistance_drop", "turn_id": "...", "context": {...}}
    ]
  },
  "ai_output": { ... },
  "human_correction": { ... }
}
```

This is the format a supervised fine-tuning pipeline can consume directly — full context per example, with structured signals rather than raw text.

---

## Implementation Phases

### Phase TP1: Enriched session_turns columns
- Alembic migration adding all new columns (nullable, zero-downtime)
- `TurnEnrichmentService` skeleton + `_reconstruct_state_timeline()`
- Wire into `SessionPostprocessService` (after grading step)
- Tests: `test_turn_enrichment_populates_emotion_columns.py`

### Phase TP2: `fact_turn_events` table + writer
- Add `FactTurnEvent` model + migration
- Implement `_write_fact_turn_events()` in `TurnEnrichmentService`
- Verify all 12 EVENT_TYPES are written correctly for a full test session
- Tests: `test_fact_turn_events_written_for_session.py`

### Phase TP3: Objection taxonomy
- Add `ObjectionType` model + migration + seed data
- Link `session_turns.objection_tags` to taxonomy on enrichment (tag → `ObjectionType.tag`)
- `GET /scenarios/objection-types` — public taxonomy endpoint for the mobile app to display coaching tips
- Tests: `test_objection_taxonomy_seed.py`

### Phase TP4: Backfill + training export upgrade
- Celery task `backfill_turn_enrichment` — processes all historical sessions
- Update `GET /admin/training-signals/export` to include full turn structure
- Tests: `test_training_export_includes_turn_structure.py`

---

## Key Files

```
backend/app/models/session.py              — MODIFY: add new columns to SessionTurn
backend/app/models/transcript.py           — NEW: FactTurnEvent, ObjectionType
backend/app/services/turn_enrichment_service.py — NEW
backend/app/services/session_postprocess_service.py — MODIFY: wire TurnEnrichmentService
backend/app/api/scenarios.py               — ADD: GET /scenarios/objection-types
backend/alembic/versions/                  — NEW: session_turns enrichment + fact_turn_events + objection_types migrations
backend/tests/test_turn_enrichment.py      — NEW
```

---

## Success Metrics

- After a completed session, all `session_turns` rows have `emotion_before`, `emotion_after`, `mb_realism_score`, `stage` populated.
- `fact_turn_events` rows exist for every session within 60s of grading completing.
- Query: `SELECT * FROM fact_turn_events WHERE event_type='resistance_drop' AND rep_id=?` runs in < 20ms with index.
- Training export includes per-turn structured data in valid JSONL format.
- Zero changes to the immutable `session_events` table or its write path.
