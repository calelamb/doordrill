# PRD: Prompt Version Runtime Wiring

**Status:** Ready for implementation
**Scope:** Backend only (`backend/`)
**Dependencies:** Existing `PromptVersion` model, `PromptExperimentService`, `GradingService` (reference implementation)

---

## Background

The `PromptVersion` table, `PromptExperimentService`, and A/B routing logic are fully built and working for the `grading_v2` prompt type. Every grading run already selects its prompt via DB-backed routing and records the chosen version ID in `GradingRun.prompt_version_id`.

The same infrastructure exists for `conversation` and `coaching` prompt types but is not yet wired at runtime:

- **Conversation:** `Session.prompt_version` stores the active version string, and `ConversationOrchestrator.bind_session_context()` receives it — but `PromptBuilder.build()` only uses it as a cosmetic label. The DB record's actual `content` is never injected into the system prompt. No A/B experiment routing exists for session creation.
- **Coaching:** `ManagerAiCoachingService` builds all prompts inline. No version tracking, no DB lookup, no audit trail.
- **Admin API:** Experiment management endpoints exist, but there are no endpoints to create, list, read, update, or activate `PromptVersion` records themselves.

---

## Goals

1. Give admins full CRUD control over `PromptVersion` records via API (no direct DB access required).
2. Wire the active `conversation` PromptVersion content into the live conversation system prompt as an injectable directive layer.
3. Route conversation sessions to control/challenger prompt versions via `PromptExperimentService` at session creation (mirrors grading A/B routing).
4. Wire the active `coaching` PromptVersion content into `ManagerAiCoachingService` prompts and record which version was used.
5. Seed a `coaching` v1 prompt version in `init_db`.
6. Add tests covering all new paths.

---

## Non-Goals

- Do not change the grading pipeline (already complete).
- Do not restructure the hardcoded `PromptBuilder` layers 1–4. The DB content is injected as an **additive** directive layer, not a replacement.
- Do not add UI changes (dashboard or mobile).

---

## Task 1: PromptVersion CRUD Admin Endpoints

**File:** `backend/app/api/admin.py`

Add the following endpoints. All require `require_manager` auth (same as existing admin endpoints).

### 1a. List prompt versions

```
GET /admin/prompt-versions?prompt_type=conversation
```

Query param `prompt_type` is optional (returns all types if omitted). Returns list ordered by `created_at desc`.

Response shape per item:
```json
{
  "id": "...",
  "prompt_type": "conversation",
  "version": "conversation_v1",
  "content": "...",
  "active": true,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

### 1b. Get single prompt version

```
GET /admin/prompt-versions/{version_id}
```

Returns 404 if not found.

### 1c. Create prompt version

```
POST /admin/prompt-versions
```

Request body:
```json
{
  "prompt_type": "conversation",
  "version": "conversation_v2",
  "content": "...",
  "active": false
}
```

- `prompt_type`: required, max 64 chars
- `version`: required, max 64 chars
- `content`: required, non-empty
- `active`: optional, default `false`

Enforce the existing unique constraint (`prompt_type` + `version`). Return 409 if duplicate. Do NOT automatically deactivate other versions on create — that is the job of the activate endpoint.

### 1d. Update prompt version content

```
PATCH /admin/prompt-versions/{version_id}
```

Request body (all fields optional):
```json
{
  "content": "...",
  "version": "conversation_v2-revised"
}
```

Only `content` and `version` string are patchable. `active` is not patchable here (use activate endpoint). Return 404 if not found.

### 1e. Activate a prompt version

```
POST /admin/prompt-versions/{version_id}/activate
```

Sets this version as `active = True` and sets all other versions of the same `prompt_type` to `active = False`. Atomic — wrap in a single transaction. Returns the updated version object. Return 404 if not found.

### Shared serializer

Add a `_serialize_prompt_version(pv: PromptVersion) -> dict` helper (similar to the existing `_serialize_prompt_experiment`) and use it in all five endpoints.

---

## Task 2: Conversation Prompt Content Injection

**Files:** `backend/app/services/conversation_orchestrator.py`, `backend/app/api/rep.py`

### 2a. Load content at session creation

In `rep.py`, the session creation endpoint already queries for the active `conversation` PromptVersion to stamp `session.prompt_version` (the version string). Extend this to:

1. Use `PromptExperimentService.get_active_experiment(db, prompt_type="conversation")` to check for a running A/B experiment.
2. If an experiment is active, use MD5 bucket routing (identical logic to `GradingService._select_prompt_version`) to pick control or challenger version.
3. If no experiment, use the active version (existing behavior).
4. Stamp `session.prompt_version` with the selected version's `.version` string (existing column — no migration needed).
5. Also retrieve the selected PromptVersion's `.content` and pass it to the response or store it in a way that `ws.py` can retrieve it when binding the session.

The cleanest approach: after selecting the version, the content is retrievable at WS bind time by querying on the version string. No schema change needed.

### 2b. Inject content in `bind_session_context`

`ConversationOrchestrator.bind_session_context()` already receives `db` and `prompt_version` (the version string). Extend it to:

1. If `db` is not None and `prompt_version` is not None, query:
   ```python
   db.scalar(
       select(PromptVersion)
       .where(PromptVersion.prompt_type == "conversation")
       .where(PromptVersion.version == prompt_version)
   )
   ```
2. If a record is found and its `content` is non-empty, store the content on the `ConversationContext` dataclass as `conversation_prompt_content: str | None = None`.

### 2c. Inject content in `PromptBuilder.build()`

`PromptBuilder.build()` currently accepts `prompt_version: str | None` (used as a label only). Extend the method signature:

```python
def build(
    self,
    ...,
    prompt_version: str | None = None,
    conversation_prompt_content: str | None = None,  # NEW
    ...
) -> str:
```

After the existing Layer 4B (edge case directives), if `conversation_prompt_content` is non-empty, add a new part:

```python
layer_five_override = (
    "LAYER 5 - PROMPT OVERRIDE DIRECTIVES\n"
    "The following directives apply to this session and take precedence over general guidance above.\n"
    f"{conversation_prompt_content.strip()}"
)
```

Add `layer_five_override` to the `parts` list before the `hard_rule`.

Pass `conversation_prompt_content=context.conversation_prompt_content` when calling `PromptBuilder.build()` from within the orchestrator's turn-processing method.

### 2d. Seed `conversation_v2` for testing

In `init_db._seed_prompt_versions()`, add a second conversation version:

```python
_upsert_prompt_version(
    db,
    prompt_type="conversation",
    version="conversation_v2",
    content=(
        "Additional directive: When the rep directly acknowledges a named concern before pivoting, "
        "respond with at least one follow-up question before returning to objection mode. "
        "Do not immediately soften — require two consecutive helpful signals to move emotion upward."
    ),
    active=False,  # not active by default; used for A/B testing
)
```

---

## Task 3: Coaching Service Prompt Versioning

**Files:** `backend/app/services/manager_ai_coaching_service.py`, `backend/app/db/init_db.py`

### 3a. Seed `coaching_v1`

In `init_db._seed_prompt_versions()`, add:

```python
_upsert_prompt_version(
    db,
    prompt_type="coaching",
    version="coaching_v1",
    content=(
        "You are a seasoned door-to-door sales manager preparing coaching feedback for your team. "
        "Be direct, evidence-based, and rep-focused. "
        "When identifying weaknesses, always cite a specific transcript moment. "
        "Avoid generic praise. Prioritize objection handling and close technique gaps."
    ),
    active=True,
)
```

### 3b. Load active coaching prompt in service

In `ManagerAiCoachingService.__init__()`, add:
```python
from app.models.prompt_version import PromptVersion
self._coaching_prompt_content: str | None = None  # lazy-loaded
```

Add a private method:
```python
def _get_coaching_system_prefix(self, db: Session) -> str:
    """Return active coaching prompt content, falling back to a hardcoded default."""
    from sqlalchemy import select
    row = db.scalar(
        select(PromptVersion)
        .where(PromptVersion.prompt_type == "coaching")
        .where(PromptVersion.active.is_(True))
        .order_by(PromptVersion.created_at.desc())
    )
    if row and row.content:
        return row.content.strip()
    return (
        "You are a seasoned door-to-door sales manager preparing coaching feedback for your team. "
        "Be direct, evidence-based, and rep-focused."
    )
```

### 3c. Inject into coaching call sites

The service makes LLM calls in several methods (e.g., one-on-one prep, rep insights, team briefing, session annotations, weekly briefing). Each constructs a `system` message string. For each call site:

1. Accept `db: Session` if not already present in method signature.
2. Call `self._get_coaching_system_prefix(db)` once per service method call.
3. Prepend the result to the existing system message content, separated by `\n\n`.

Specifically target these methods (they make LLM calls via `httpx`):
- `generate_one_on_one_prep`
- `generate_rep_insights`
- `generate_session_annotations`
- `generate_team_coaching_summary`
- `generate_weekly_team_briefing`
- `classify_manager_chat_intent` (if it has a system message)

Do not change response parsing, caching, or error handling logic in these methods.

---

## Task 4: Tests

**Directory:** `backend/tests/`

### 4a. `test_prompt_version_admin_api.py`

Test all five CRUD endpoints:
- `POST /admin/prompt-versions` — creates successfully, returns 409 on duplicate type+version
- `GET /admin/prompt-versions` — returns all; filters by `prompt_type` param
- `GET /admin/prompt-versions/{id}` — returns 404 for unknown ID
- `PATCH /admin/prompt-versions/{id}` — updates content; returns 404 for unknown ID
- `POST /admin/prompt-versions/{id}/activate` — sets active=True, deactivates siblings of same type; returns 404 for unknown ID

Use the existing `client` and `seed_org` fixtures from `conftest.py`. Auth via manager token.

### 4b. `test_conversation_prompt_injection.py`

Test that:
- When a `conversation` PromptVersion with non-empty content is active, `bind_session_context` stores the content on the context object
- `PromptBuilder.build()` with `conversation_prompt_content` set includes "LAYER 5 - PROMPT OVERRIDE DIRECTIVES" in the output
- `PromptBuilder.build()` with `conversation_prompt_content=None` does not include the layer 5 override header

Use unit-style tests (no DB required for builder tests). For context binding, use an in-memory SQLite session (same pattern as other orchestrator tests).

### 4c. `test_conversation_ab_routing.py`

Test that:
- When a `conversation` experiment is active, session creation stamps `session.prompt_version` with either the control or challenger version string
- The same session_id always routes to the same version (determinism)
- When no experiment is active, session creation stamps the single active version

Mirror the structure of `test_prompt_routing_is_deterministic.py`.

### 4d. `test_coaching_prompt_injection.py`

Test that:
- `_get_coaching_system_prefix` returns the active coaching prompt content when present
- Falls back to hardcoded string when no active coaching version exists
- One-on-one prep and rep insights system messages include the coaching prefix

Use mock DB with seeded PromptVersion records.

---

## Acceptance Criteria

- [ ] All five PromptVersion admin endpoints return correct HTTP status codes and serialized responses
- [ ] `POST /admin/prompt-versions/{id}/activate` atomically sets one active and deactivates all others of the same type
- [ ] Session creation routes to a conversation PromptVersion (experiment or active fallback) and stamps `session.prompt_version`
- [ ] `PromptBuilder.build()` output includes Layer 5 content when a version with content is active
- [ ] `PromptBuilder.build()` output is unchanged when no override content is present (backward compat)
- [ ] `ManagerAiCoachingService` LLM calls include the coaching prompt prefix in the system message
- [ ] All new tests pass; no existing tests broken
- [ ] `init_db` seeds `conversation_v2` (inactive) and `coaching_v1` (active) without errors

---

## Reference Files

- **Grading reference implementation:** `backend/app/services/grading_service.py` — `_select_prompt_version()` and `_ensure_active_prompt_version()` are the exact pattern to replicate for conversation routing.
- **Existing experiment service:** `backend/app/services/prompt_experiment_service.py`
- **Existing admin endpoints:** `backend/app/api/admin.py` — follow existing auth, serializer, and error handling patterns exactly.
- **Orchestrator:** `backend/app/services/conversation_orchestrator.py` — `PromptBuilder`, `bind_session_context`, `ConversationContext` dataclass
- **Session creation:** `backend/app/api/rep.py` — where `session.prompt_version` is currently stamped
- **Seed data:** `backend/app/db/init_db.py` — `_seed_prompt_versions()` and `_upsert_prompt_version()`
- **Existing tests:** `backend/tests/test_prompt_routing_is_deterministic.py`, `backend/tests/test_prompt_version_is_loaded.py`
