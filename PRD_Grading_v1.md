# PRD: Grading System Refinement — v1
**For:** Codex
**Owner:** Cale
**Status:** Ready for Implementation
**Touches:** `grading_service.py`, `schemas/scorecard.py`, `session_postprocess_service.py`

---

## Background & Goal

The grading pipeline exists and runs end-to-end. The problems are:

1. **Scores cluster at 6–7.** The LLM has no rubric anchors, so it defaults to the middle of the range. A rep who bombed and a rep who was decent both get 6.8.
2. **The fallback grader is noise.** If the LLM call fails, `opening = 6.0 + depth * 0.3` — that's measuring session length, not sales performance.
3. **One blocking LLM call.** The manager dashboard sees nothing for 5–10 seconds while the full JSON assembles. No partial delivery.
4. **`ai_summary` is 400 chars.** That's ~55 words. Not enough to tell a rep what happened and what to fix.
5. **Weakness tags are derived from score thresholds**, not observed behavior. A rep who scored 7.2 on `objection_handling` but was clearly evasive won't get flagged.
6. **No definition of what a "4" vs "7" vs "9" means.** The grading LLM is told to "be strict and evidence-based" but has no calibration.

---

## Feature Specs

---

### GR-01: Per-Category Scoring Rubrics

**Problem:** The grading prompt sends the schema and says "be strict." The LLM has no examples of what a 3, 6, or 9 looks like for each category, so it defaults to the middle.

**File:** `grading_service.py` → `GradingPromptBuilder`

**What to Build:**

Add `CATEGORY_RUBRICS` as a module-level constant and inject it into the grading prompt:

```python
CATEGORY_RUBRICS = {
    "opening": {
        "description": "How the rep introduced themselves and established the reason for the visit.",
        "anchors": {
            "9-10": "Clear name + company + specific reason for visit. Acknowledged the homeowner's time. Felt natural, not scripted. Homeowner stayed engaged.",
            "7-8":  "Introduced themselves but reason for visit was vague. Rapport attempt was present but slightly robotic.",
            "5-6":  "Skipped intro or gave a generic opener ('I'm in the neighborhood'). No rapport attempt.",
            "1-4":  "No introduction, jumped straight to pitch or close. Created immediate resistance.",
        },
    },
    "pitch_delivery": {
        "description": "How the rep explained the product/service and made the value case.",
        "anchors": {
            "9-10": "One clear benefit tied to this homeowner's specific situation. Used concrete details (price range, process). No filler.",
            "7-8":  "Value was communicated but generic. Could apply to any homeowner. Not tailored.",
            "5-6":  "Pitch was present but buried in features. Homeowner had to ask what it actually costs or does.",
            "1-4":  "No pitch, or pitch was confusing/irrelevant. Homeowner showed no comprehension of the offer.",
        },
    },
    "objection_handling": {
        "description": "How the rep responded when the homeowner raised concerns or resistance.",
        "anchors": {
            "9-10": "Acknowledged the specific objection, reframed it with evidence, and reduced friction. Homeowner moved toward curious or interested.",
            "7-8":  "Addressed the objection but reframe was generic. Homeowner softened slightly but objection wasn't fully resolved.",
            "5-6":  "Rep acknowledged the objection but didn't resolve it. Changed subject or repeated the original claim.",
            "1-4":  "Rep ignored, dismissed, or talked over the objection. Homeowner escalated or ended the conversation.",
        },
    },
    "closing_technique": {
        "description": "How the rep asked for the next step or commitment.",
        "anchors": {
            "9-10": "Asked for a specific, low-friction next step at the right moment. Framing was confident but not pushy. Homeowner agreed or gave a qualified response.",
            "7-8":  "Close attempt was present but too early or too vague ('Does that sound good?'). Homeowner deflected.",
            "5-6":  "Rep hinted at wanting to move forward but never actually asked. Or asked too many times.",
            "1-4":  "No close attempt, or used hard-pressure close ('Sign today', 'Right now'). Homeowner rejected immediately.",
        },
    },
    "professionalism": {
        "description": "Overall tone, pacing, and conduct throughout the session.",
        "anchors": {
            "9-10": "Steady throughout. Never flustered. Handled resistance with composure. Pacing felt natural.",
            "7-8":  "Generally professional but one or two moments of unnecessary filler, rushing, or breaking character.",
            "5-6":  "Noticeable tone issues — too eager, defensive, or apologetic. Affected the homeowner's trust.",
            "1-4":  "Unprofessional conduct: interrupting, dismissing concerns, getting frustrated, or asking for hints.",
        },
    },
}
```

Inject into the grading prompt as a RUBRICS block, before the schema:

```python
def _build_rubric_block(self) -> str:
    lines = ["SCORING RUBRICS — use these to calibrate your scores. Do not compress scores into 6–7. Use the full 0–10 range.\n"]
    for key, rubric in CATEGORY_RUBRICS.items():
        lines.append(f"{key.upper()} — {rubric['description']}")
        for range_label, description in rubric["anchors"].items():
            lines.append(f"  {range_label}: {description}")
        lines.append("")
    return "\n".join(lines)
```

**Acceptance Criteria:**
- Grading prompt includes a RUBRICS block before the schema
- The rubric block is injected on every call, not only when session_context is provided
- A rep who opened with hard close language should score ≤ 4 on `opening`
- A rep who gave a perfect opening should score ≥ 9 on `opening`
- Score distribution across a batch of 10 test sessions should span at least 3 points (e.g., not all 6.5–7.2)

---

### GR-02: Score Distribution Calibration Guard

**Problem:** Even with rubrics, LLMs drift toward safe middle scores. Need an explicit calibration instruction.

**File:** `grading_service.py` → `GradingPromptBuilder.template_blueprint()`

**What to Build:**

Add a calibration block to `template_blueprint()`:

```python
SCORE_CALIBRATION_INSTRUCTION = (
    "SCORE CALIBRATION: Use the full 0–10 range. Do not default to 6–7 for everything.\n"
    "  - 9–10: Genuinely exceptional. Evidence is clear, specific, and impactful.\n"
    "  - 7–8:  Competent. The rep did this correctly but left clear room for improvement.\n"
    "  - 5–6:  Below average. Present but not effective. The homeowner was not moved.\n"
    "  - 1–4:  Poor. Active mistakes that hurt the session.\n"
    "  - 0:    Absent. The rep did not attempt this at all.\n"
    "If all five of your category scores land between 6.0 and 7.5, recalibrate — "
    "that range should only be used when every category is genuinely middle-of-the-road.\n"
)
```

**Acceptance Criteria:**
- The calibration block is in every grading prompt
- `test_grading_engine_v2.py` asserts the string "Use the full 0–10 range" appears in the prompt

---

### GR-03: Behavior-Signal-Based Fallback Grader

**Problem:** The current fallback grader computes `opening = 6.0 + depth * 0.3` — session length, not quality. If the LLM is unavailable, reps get random scores that go into the manager dashboard.

**File:** `grading_service.py` → `_grade_with_fallback()`

**What to Build:**

Replace the heuristic scoring with a signal-based computation using `turn.behavioral_signals` (already stored on `SessionTurn`):

```python
SIGNAL_SCORE_MAP: dict[str, dict[str, float]] = {
    "opening": {
        "builds_rapport":        +1.5,
        "mentions_social_proof": +1.0,
        "neutral_delivery":      -0.5,
        "pushes_close":          -2.5,
        "dismisses_concern":     -2.0,
    },
    "pitch_delivery": {
        "explains_value":        +1.5,
        "personalizes_pitch":    +1.0,
        "provides_proof":        +0.8,
        "neutral_delivery":      -0.5,
        "pushes_close":          -1.0,
    },
    "objection_handling": {
        "acknowledges_concern":  +2.0,
        "explains_value":        +1.0,
        "reduces_pressure":      +1.0,
        "provides_proof":        +1.0,
        "ignores_objection":     -2.5,
        "dismisses_concern":     -2.5,
        "high_difficulty_backfire": -1.5,
    },
    "closing_technique": {
        "invites_dialogue":      +1.0,
        "reduces_pressure":      +0.5,
        "pushes_close":          -1.5,   # premature/hard close
    },
    "professionalism": {
        "builds_rapport":        +0.5,
        "personalizes_pitch":    +0.5,
        "acknowledges_concern":  +0.5,
        "dismisses_concern":     -1.5,
        "pushes_close":          -1.0,
    },
}

def _score_from_signals(
    self,
    rep_turns: list[Any],
    category_key: str,
    stage_hints: set[str],
) -> float:
    base = 6.0
    relevant_turns = [
        t for t in rep_turns
        if not stage_hints or t.stage in stage_hints
    ] or rep_turns
    category_signals = SIGNAL_SCORE_MAP.get(category_key, {})
    for turn in relevant_turns:
        for signal in (turn.behavioral_signals or []):
            base += category_signals.get(signal, 0.0)
    return round(max(0.0, min(10.0, base)), 1)
```

Replace the heuristic score calculation in `_grade_with_fallback()` with `_score_from_signals()` per category.

**Acceptance Criteria:**
- A fallback session where all rep turns have `pushes_close` + `ignores_objection` scores ≤ 4.0 on `objection_handling`
- A fallback session where all rep turns have `acknowledges_concern` + `explains_value` scores ≥ 7.5 on `objection_handling`
- Fallback scores no longer correlate with session length alone
- `test_grading_engine_v2.py` has a test for this behavior

---

### GR-04: Expanded `ai_summary` + Structured Coaching Narrative

**Problem:** `ai_summary` is capped at 400 chars (~55 words). That's barely a sentence per category. Reps get "You kept control of the drill but need clearer objection reframing" — which tells them nothing actionable.

**File:** `schemas/scorecard.py` + `grading_service.py`

**What to Build:**

Expand `ai_summary` limit in `StructuredScorecardPayloadV2` from 400 to 700 characters:

```python
# schemas/scorecard.py
ai_summary: str = Field(min_length=1, max_length=700)
```

Update `_clip_text` call in `_normalize_grading()` to match: `limit=700`.

Update the grading prompt to enforce a 3-part structure:

```python
AI_SUMMARY_INSTRUCTION = (
    "ai_summary format (max 700 chars, second person, plain English, no jargon):\n"
    "  Sentence 1: What the rep did well — specific, with evidence ('You opened with a neighbor reference that worked').\n"
    "  Sentence 2: The moment things shifted — the specific turn where the conversation changed and why.\n"
    "  Sentence 3: The one concrete fix — not a category name, a specific behavior ('Next time, acknowledge the price objection before explaining value').\n"
    "Do not start with 'Overall' or 'In this session'. Start with what the rep did.\n"
)
```

**Acceptance Criteria:**
- `ai_summary` schema allows up to 700 chars (no schema migration needed if the DB column is text)
- Grading prompt instructs the 3-part structure
- `_clip_text(..., limit=700)` in `_normalize_grading`
- Fallback `ai_summary` also updated to follow the 3-part structure

---

### GR-05: Behavior-Driven Weakness Tags

**Problem:** `weakness_tags` are assigned when `score < 7.0`. A rep who scored 7.2 on `objection_handling` but had `ignores_objection` signals on multiple turns won't get flagged. Conversely, a rep who scored 6.9 but was solid on objections except for one bad turn gets permanently tagged "weak objection handler."

**File:** `grading_service.py`

**What to Build:**

Compute weakness tags from behavioral signals, not just score thresholds:

```python
WEAKNESS_TAG_SIGNAL_TRIGGERS: dict[str, list[str]] = {
    "objection_handling": ["ignores_objection", "dismisses_concern", "high_difficulty_backfire"],
    "closing_technique":  ["pushes_close"],   # premature hard close
    "opening":            ["neutral_delivery", "pushes_close"],
    "pitch_delivery":     ["neutral_delivery"],
    "professionalism":    ["dismisses_concern", "pushes_close"],
}
WEAKNESS_TAG_SIGNAL_THRESHOLD = 2   # fires if signal appears in >= 2 rep turns

def _derive_weakness_tags(
    self,
    category_scores: dict[str, Any],
    rep_turns: list[Any],
) -> list[str]:
    tags: set[str] = set()
    # Score-based (keep as secondary signal)
    for key, value in category_scores.items():
        if float(value.get("score", 10)) < 6.5:
            tags.add(key)
    # Signal-based (primary)
    signal_counts: dict[str, int] = {}
    for turn in rep_turns:
        for signal in (turn.behavioral_signals or []):
            signal_counts[signal] = signal_counts.get(signal, 0) + 1
    for tag, triggers in WEAKNESS_TAG_SIGNAL_TRIGGERS.items():
        if any(signal_counts.get(s, 0) >= WEAKNESS_TAG_SIGNAL_THRESHOLD for s in triggers):
            tags.add(tag)
    return sorted(tags)
```

**Acceptance Criteria:**
- A rep with 2+ `ignores_objection` turns is tagged `objection_handling` even if score is 7.5
- A rep with 2+ `pushes_close` turns is tagged `closing_technique`
- A clean rep with no weak signals and all scores ≥ 7.0 has empty weakness_tags
- Signal-based tags are computed in both LLM path (`_normalize_grading`) and fallback path

---

### GR-06: Grading Latency — Faster Model + Timeout Guard

**Problem:** `grade_session()` makes one LLM call with the full transcript + schema + rubrics. On a long session (20+ turns), this is 1500+ tokens in, and the response wait is 6–12 seconds. The manager dashboard blocks on this.

**File:** `grading_service.py` + `core/config.py`

**What to Build:**

**Part A — Model selection.** Add a `grading_model` setting that defaults to `gpt-4o-mini` (fast, cheap, good at structured JSON) rather than inheriting the general `openai_model` which may be gpt-4o.

```python
# core/config.py
grading_model: str = Field(default="gpt-4o-mini", alias="GRADING_MODEL")
```

Use `self.settings.grading_model` in `_grade_with_llm()` instead of `self.settings.openai_model`.

**Part B — Timeout guard.** Add a hard 20-second timeout on the grading LLM call specifically (separate from `provider_timeout_seconds` which is shared):

```python
# core/config.py
grading_timeout_seconds: float = Field(default=20.0, alias="GRADING_TIMEOUT_SECONDS")
```

Use `httpx.AsyncClient(timeout=self.settings.grading_timeout_seconds)` in `_grade_with_llm()`.

**Part C — Async post-process trigger.** Confirm that `grade_session()` is called from `session_postprocess_service.py` in a background task, not blocking the end-session API response. If it's currently blocking, move it to a background task:

```python
# session_postprocess_service.py
# After session is marked ended and committed, fire grading in background:
import asyncio

async def _grade_in_background(self, db_session_factory, session_id: str) -> None:
    async with db_session_factory() as db:
        try:
            await self.grading_service.grade_session(db, session_id)
        except Exception:
            logger.exception("Background grading failed for session %s", session_id)
```

If background task dispatch is already in place, skip this sub-task and just document it.

**Acceptance Criteria:**
- `grading_model` setting exists and defaults to `gpt-4o-mini`
- Grading LLM call uses `grading_timeout_seconds` (default 20s), not the shared provider timeout
- End-session API response does not block on grading completion
- Manager dashboard receives the scorecard via the existing webhook/push mechanism, not inline in the API call
- If grading times out, fallback grader result is stored immediately and a retry is queued

---

### GR-07: Grading Prompt Length Guard

**Problem:** With rubrics (GR-01) + session context (G-04 from v3 PRD) + inflection points (G-07 from v3 PRD) + transcript, long sessions could push the grading prompt past 4000 tokens. That increases cost and latency.

**File:** `grading_service.py`

**What to Build:**

Add a transcript trimming step before building the prompt. For long sessions, include only the first 2 turns, all objection_handling turns, and the last 2 turns:

```python
MAX_TRANSCRIPT_TURNS_FOR_GRADING = 20

def _select_grading_turns(self, turns: list[Any]) -> list[Any]:
    if len(turns) <= MAX_TRANSCRIPT_TURNS_FOR_GRADING:
        return turns
    first_two = turns[:2]
    last_two = turns[-2:]
    objection_turns = [
        t for t in turns[2:-2]
        if t.stage == "objection_handling" or bool(getattr(t, "objection_tags", None))
    ]
    close_turns = [
        t for t in turns[2:-2]
        if t.stage == "close_attempt"
    ]
    middle = list(dict.fromkeys([*objection_turns, *close_turns]))
    selected = list(dict.fromkeys([*first_two, *middle, *last_two]))
    return selected[:MAX_TRANSCRIPT_TURNS_FOR_GRADING]
```

Use `_select_grading_turns(turns)` when building the prompt in `_grade_with_llm()`.

**Acceptance Criteria:**
- A 30-turn session produces a grading prompt using at most 20 turns
- The selected turns always include at least the first 2 and last 2 turns
- Objection_handling and close_attempt turns are prioritized in the middle
- `test_grading_engine_v2.py` has a test asserting the trimming behavior

---

## Implementation Notes for Codex

### File Targets

| Feature | File | Type |
|---|---|---|
| GR-01 Rubrics | `grading_service.py` → `GradingPromptBuilder` | New constant + inject |
| GR-02 Calibration guard | `grading_service.py` → `template_blueprint()` | Additive |
| GR-03 Signal-based fallback | `grading_service.py` → `_grade_with_fallback()` | Replace scoring logic |
| GR-04 Expanded summary | `schemas/scorecard.py` + `grading_service.py` | Schema + prompt change |
| GR-05 Behavior-driven tags | `grading_service.py` → `_normalize_grading()` + `_grade_with_fallback()` | New method |
| GR-06 Latency | `core/config.py` + `grading_service.py` + `session_postprocess_service.py` | Config + wiring |
| GR-07 Prompt length guard | `grading_service.py` → `_grade_with_llm()` | New method |

### Priority Order

1. **GR-03** — Fix the fallback first. It's a regression risk; bad fallback scores go into analytics.
2. **GR-01 + GR-02** together — Both are prompt changes, ship in one commit.
3. **GR-05** — Behavior-driven weakness tags. Improves signal quality in the dashboard.
4. **GR-04** — Expanded summary. Schema change + prompt change, small but visible to reps.
5. **GR-06** — Latency. Confirm background task wiring, add config.
6. **GR-07** — Prompt length guard. Last because it depends on GR-01 being in place to know true prompt size.

### Tests to Write / Update

- `test_grading_engine_v2.py`:
  - Assert rubric block appears in grading prompt (GR-01)
  - Assert calibration string appears (GR-02)
  - Assert fallback scores respond to behavioral signals (GR-03)
  - Assert `ai_summary` limit is 700 in schema (GR-04)
  - Assert weakness tags fire from signals even when score ≥ 7.0 (GR-05)
  - Assert `_select_grading_turns` returns ≤ 20 turns for a 30-turn input (GR-07)

### Do Not Change

- `StructuredScorecardPayloadV2` field names — mobile and manager dashboard read these
- `CATEGORY_KEYS` list and order — analytics aggregation depends on this
- `CATEGORY_WEIGHTS` — changing weights changes historical score comparisons
- `Scorecard` ORM model — no DB migration in this PRD
- The grading prompt version system (`prompt_version_resolver`) — rubrics go into the built prompt, not as a stored version

---

## What "Done" Looks Like

After these changes a manager should be able to:
1. Open a session scorecard and immediately understand *why* each score is what it is — specific language, not "below average performance."
2. See weakness tags that reflect what actually happened, not just a score threshold.
3. Read an `ai_summary` that tells the rep exactly what moment turned the conversation and what to do differently.

And grading should complete within 8 seconds on a typical session, not 15+.
