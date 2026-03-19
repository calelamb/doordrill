# PRD: Multi-Tenant Org Config & Prompt Isolation

**Status:** Ready for implementation
**Scope:** Backend — models, migrations, `conversation_orchestrator.py`, `grading_service.py`, admin API
**Depends on:** None — this is the foundation layer for all company-agnostic features
**Blocks:** PRD: Material Ingestion, Questionnaire & Prompt Studio

---

## Background

DoorDrill's prompt system currently has no concept of per-company configuration. `PromptVersion` records have no `org_id`, persona definitions are embedded in prompt text, and the `PromptBuilder` layers contain content that is implicitly specific to one company's pitch. A second company onboarding today would overwrite the same global records.

This PRD establishes the data model foundation for a fully company-agnostic platform. Every company gets their own prompt configuration. The global defaults remain as fallbacks so existing behavior is fully preserved.

---

## Non-Goals

- No UI for managers in this PRD — that is PRD 2.
- No material ingestion in this PRD.
- No changes to the voice WebSocket hot path or latency profile.
- No changes to the existing `PromptExperiment` A/B system.

---

## Data Model

### 1. `OrgPromptConfig`

**File:** `backend/app/models/org_prompt_config.py` (new file)

This is the structured company knowledge record. One row per org. It stores the key business facts about the company that feed into prompt generation and the `PromptBuilder` layers. It is **not** raw prompt text — it is structured data that the system uses to render prompt content.

```python
class OrgPromptConfig(Base):
    __tablename__ = "org_prompt_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    # Core business identity
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    product_category: Mapped[str] = mapped_column(String, nullable=False)
    # e.g. "residential solar", "home security", "pest control", "fiber internet"

    product_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 2-4 sentence plain-English description of what they sell

    # Pitch structure
    pitch_stages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Ordered list of stage names, e.g.:
    # ["door_knock", "initial_pitch", "objection_handling", "considering", "close_attempt", "ended"]
    # These map to the ConversationOrchestrator stage machine.
    # If null, falls back to the global stage list.

    # Value proposition
    unique_selling_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # List of strings: ["No upfront cost", "25-year warranty", "Average savings of $180/mo"]

    # Objection library
    known_objections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # List of objects: [{"objection": "I rent, not own", "preferred_rebuttal_hint": "..."}]
    # "preferred_rebuttal_hint" is a coaching signal, not a script — it guides grading.

    # Homeowner persona parameters
    target_demographics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # e.g. {"age_range": "35-65", "homeowner_type": "suburban", "income_bracket": "middle",
    #        "common_concerns": ["cost", "installation disruption", "HOA rules"]}

    # Competitor awareness
    competitors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # [{"name": "SunPower", "key_differentiator": "We offer battery backup, they don't"}]

    # Pricing context (not actual prices — framing language for the AI persona)
    pricing_framing: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. "Pricing is based on system size. Rep should not quote specific numbers until site survey."

    # Tone and close style (from questionnaire)
    close_style: Mapped[str | None] = mapped_column(String, nullable=True)
    # "consultative" | "assumptive" | "urgency-based"

    rep_tone_guidance: Mapped[str | None] = mapped_column(String, nullable=True)
    # "professional_warm" | "casual_friendly" | "technical_expert"

    # Grading configuration
    grading_priorities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Ordered list of what matters most in grading for this org:
    # ["rapport_building", "objection_handling", "value_prop_clarity", "close_attempt"]
    # Used to weight grading rubric in GradingService.

    # Status
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # False = draft (from Prompt Studio, not yet live). True = active for rep sessions.

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_org_prompt_configs_org_published", "org_id", "published"),
    )
```

---

### 2. Org-Scope `PromptVersion`

**File:** `backend/app/models/prompt_version.py` (modify existing)

Add `org_id` as a nullable column:

```python
org_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
```

Semantics:
- `org_id = NULL` → global default, applies to all orgs that have no org-specific override
- `org_id = "acme_solar"` → applies only to that org

Update the unique constraint:

```python
# Old:
UniqueConstraint("prompt_type", "version")

# New:
UniqueConstraint("prompt_type", "version", "org_id", name="uq_prompt_version_type_version_org")
```

This allows `conversation/v1` to exist as both a global default and an org-specific version simultaneously.

Update the active index:

```python
Index("ix_prompt_version_type_active_org", "prompt_type", "active", "org_id")
```

---

### 3. Migration

**File:** `backend/alembic/versions/XXXX_org_prompt_config_and_prompt_version_org_scoping.py`

- Create `org_prompt_configs` table with all columns above.
- Add `org_id` nullable column to `prompt_versions`.
- Drop the old unique constraint on `prompt_versions`, add the new three-column one.
- Add the new index on `prompt_versions`.
- No data migration needed — existing rows have `org_id = NULL` (global default), which is correct.

---

## Service Layer

### 4. `OrgPromptConfigService`

**File:** `backend/app/services/org_prompt_config_service.py` (new file)

```python
class OrgPromptConfigService:

    def get_config(self, org_id: str, db: Session) -> OrgPromptConfig | None:
        """Returns the published config for this org, or None if not yet configured."""

    def get_or_create_draft(self, org_id: str, db: Session) -> OrgPromptConfig:
        """Returns existing config (any status) or creates a blank draft."""

    def update_config(self, org_id: str, updates: dict, db: Session) -> OrgPromptConfig:
        """Partial update — merges updates into existing fields."""

    def publish_config(self, org_id: str, db: Session) -> OrgPromptConfig:
        """
        Sets published=True and triggers PromptVersionSynthesizer.synthesize_for_org().
        This generates org-specific PromptVersion records from the config.
        See Task 6 below.
        """

    def get_active_config(self, org_id: str, db: Session) -> OrgPromptConfig | None:
        """
        Returns published config for org. Used by orchestrator at session bind.
        Result is cached in memory (TTLCache, 5 min) per org_id to avoid
        per-turn DB hits.
        """
```

---

### 5. `PromptVersionResolver` — Org-Aware Version Selection

**File:** `backend/app/services/prompt_version_resolver.py` (new file — extracted from grading_service.py pattern)

Currently each service (grading, conversation orchestrator) has its own version selection logic. Extract this into a shared resolver that is org-aware:

```python
class PromptVersionResolver:

    def resolve(
        self,
        prompt_type: str,
        org_id: str | None,
        session_id: str,
        db: Session,
    ) -> PromptVersion:
        """
        Resolution order:
        1. Check for active PromptExperiment for this prompt_type + org_id.
           If found, use MD5 bucket routing (existing logic from grading_service).
        2. Check for an active org-specific PromptVersion (org_id matches, active=True).
        3. Fall back to active global PromptVersion (org_id IS NULL, active=True).
        4. If none found, call _ensure_active_prompt_version() to seed from defaults.

        Records prompt_version_id resolution in a lightweight cache on the
        session object so the same version is used for the full session duration.
        """
```

**Update all existing callers to use `PromptVersionResolver`:**
- `grading_service.py`: replace inline `_select_prompt_version()` with `PromptVersionResolver.resolve()`
- `conversation_orchestrator.py`: replace `bind_session_context()` version lookup with `PromptVersionResolver.resolve()`
- Any coaching service prompt lookup (from PRD 1 — Prompt Version Runtime)

This deduplicates logic and ensures consistent org-aware resolution everywhere.

---

### 6. `PromptVersionSynthesizer`

**File:** `backend/app/services/prompt_version_synthesizer.py` (new file)

When a manager publishes their `OrgPromptConfig`, this service generates org-specific `PromptVersion` records for all prompt types, populated with the org's data.

```python
class PromptVersionSynthesizer:

    def synthesize_for_org(self, config: OrgPromptConfig, db: Session) -> dict[str, PromptVersion]:
        """
        Generates (or updates) org-specific PromptVersion records for:
        - prompt_type="conversation" — injects company name, product, USPs,
          objections, persona demographics, close style into the Layer 2/3 templates
        - prompt_type="grading" — injects grading_priorities to weight rubric criteria
        - prompt_type="coaching" — injects preferred_rebuttal_hints for each objection

        Uses Jinja2 templates (see Task 6a below) to render each prompt type
        from the structured config data.

        Sets org_id on each created PromptVersion. Deactivates any prior
        org-specific version of the same prompt_type before activating the new one.

        Returns dict mapping prompt_type → PromptVersion.
        """
```

#### 6a. Jinja2 Prompt Templates

**Directory:** `backend/app/prompt_templates/` (new directory)

Create base Jinja2 templates for each prompt type. These are the "skeleton" prompts that get filled in with org-specific data:

- `conversation_base.j2` — renders Layers 1–4B with `{{ company_name }}`, `{{ product_description }}`, `{{ unique_selling_points }}`, `{{ known_objections }}`, `{{ target_demographics }}`, `{{ close_style }}`, etc. as template variables.
- `grading_base.j2` — renders the grading rubric with `{{ grading_priorities }}` weighting injected.
- `coaching_base.j2` — renders coaching guidance with `{{ known_objections }}` and their `preferred_rebuttal_hint` values.

The existing global prompt content in `init_db.py` seeds become the default values for these templates when `org_id` is null.

---

### 7. `ConversationOrchestrator` — Org Config Integration

**File:** `backend/app/services/conversation_orchestrator.py`

#### 7a. `ConversationContext` — add `org_config`

```python
@dataclass
class ConversationContext:
    # ... existing fields ...
    org_config: OrgPromptConfig | None = None  # NEW
```

#### 7b. `bind_session_context()` — load org config

After the existing `conversation_prompt_content` resolution, add:

```python
context.org_config = OrgPromptConfigService().get_active_config(session.org_id, db)
```

#### 7c. `PromptBuilder.build()` — inject org config as Layer 0

If `org_config` is present and published, inject a new **Layer 0** immediately before Layer 1:

```
=== COMPANY CONTEXT ===
You are roleplaying as a homeowner being approached by a rep from {company_name}.
They sell {product_category}: {product_description}
Target customer profile: {target_demographics summary}
Close style expected from rep: {close_style}
```

This layer is intentionally brief (< 100 tokens). Its purpose is to anchor the AI homeowner's worldview to the specific company's context before the immersion and persona layers fire. It does not replace Layers 1–5; it precedes them.

If `org_config` is None or not published, Layer 0 is omitted and behavior is identical to today.

---

## Admin API Endpoints

**File:** `backend/app/api/admin.py`

Add the following endpoints. All require admin authentication.

```
GET    /admin/orgs/{org_id}/prompt-config
       Returns the org's OrgPromptConfig (draft or published).

PUT    /admin/orgs/{org_id}/prompt-config
       Full or partial update to the config (used by Prompt Studio in PRD 2).
       Body: any subset of OrgPromptConfig fields as JSON.

POST   /admin/orgs/{org_id}/prompt-config/publish
       Publishes the config: sets published=True, triggers PromptVersionSynthesizer.
       Returns the generated PromptVersion records.

GET    /admin/orgs/{org_id}/prompt-config/preview
       Renders a preview of the synthesized conversation prompt (Layer 0 + synthesized
       PromptVersion content) without writing to DB. Used by Prompt Studio UI.

GET    /admin/prompt-versions?org_id={org_id}&prompt_type={type}
       Already exists — ensure it filters by org_id correctly now that the
       column exists. Update query to support org_id as an optional filter param.
```

---

## Acceptance Criteria

- [ ] `org_prompt_configs` table exists with all columns; migration runs clean
- [ ] `prompt_versions.org_id` column exists; old unique constraint replaced; new index created
- [ ] `PromptVersionResolver.resolve()` returns org-specific version when one exists, falls back to global when not
- [ ] All existing callers (grading, orchestrator, coaching) use `PromptVersionResolver`
- [ ] `ConversationContext.org_config` is loaded at session bind; `None` when org has no published config
- [ ] `PromptBuilder.build()` prepends Layer 0 when org_config is published; no Layer 0 when it is None
- [ ] `PromptVersionSynthesizer.synthesize_for_org()` generates conversation + grading + coaching PromptVersions from config
- [ ] `POST /admin/orgs/{org_id}/prompt-config/publish` triggers synthesis and returns generated versions
- [ ] `GET /admin/orgs/{org_id}/prompt-config/preview` renders prompt without DB writes
- [ ] Existing sessions with no org config are entirely unaffected — behavior identical to pre-PRD
- [ ] System prompt token count (from latency PRD Task 4) stays under hard limit after Layer 0 addition

---

## Reference Files

- `backend/app/models/prompt_version.py`
- `backend/app/models/` (add `org_prompt_config.py`)
- `backend/app/services/grading_service.py` (existing version resolution pattern to extract)
- `backend/app/services/conversation_orchestrator.py`
- `backend/app/services/prompt_experiment_service.py`
- `backend/app/api/admin.py`
- `backend/alembic/versions/`
