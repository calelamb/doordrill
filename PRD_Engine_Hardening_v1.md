# PRD: Engine Hardening — v1
**For:** Codex
**Owner:** Cale
**Status:** Ready for Implementation
**Touches:** `conversation_orchestrator.py`, `transcript_normalization_service.py`, `adaptive_training_service.py`

---

## Background

These are concrete logic bugs and gaps found through static analysis — no live test needed to confirm them. Each one is self-contained and low-risk to ship. Implement in the priority order at the bottom.

---

## Feature Specs

---

### H-01: Rep Monologue Detection

**Problem:** The signal detection system tracks what the rep says but not how long they've been talking without asking a question. A rep who monologues for 3+ turns — pitching without pausing for the homeowner — is practicing bad technique, and the homeowner gets no signal to disengage or show impatience. This is one of the most common real D2D failure patterns.

**File:** `conversation_orchestrator.py`

**What to Build:**

Add `rep_monologue_streak: int = 0` to `ConversationState`. Increment when the rep turn has no `invites_dialogue` signal and no `?` in the text. Reset to 0 when `invites_dialogue` fires.

```python
def _update_monologue_streak(state: ConversationState, analysis: TurnAnalysis) -> None:
    if "invites_dialogue" in analysis.behavioral_signals:
        state.rep_monologue_streak = 0
    else:
        state.rep_monologue_streak = min(5, state.rep_monologue_streak + 1)
```

Wire this into the reaction_intent override at threshold:

```python
# Inside _reaction_intent, before other checks:
if state.rep_monologue_streak >= 3:
    return (
        "The rep has been talking for several turns without asking you anything. "
        "Real homeowners tune out when they're being lectured. "
        "Show disengagement: glance back inside, give a one-word response, "
        "or ask bluntly 'Is there a point to this?' "
        "Do not stay engaged as if the monologue is fine."
    )
```

At streak >= 5, escalate to posture `defensive` regardless of current emotion.

Add `rep_monologue_streak` to the `HARMFUL_SIGNALS` check in the grading context block (G-04 / GR-05) so prolonged monologues get flagged as a weakness.

**Acceptance Criteria:**
- `rep_monologue_streak` increments each turn the rep doesn't ask a question
- At streak == 3, `reaction_intent` contains disengagement language
- At streak == 5, `homeowner_posture` is forced to `defensive`
- Streak resets when `invites_dialogue` fires
- `test_conversation_orchestrator.py` has a test: 3 non-question turns → disengagement language in reaction_intent

---

### H-02: Response Cap / Sentence Rule Deconfliction

**Problem:** The LLM receives two competing length constraints simultaneously:
- `sentence_rule`: "Respond in no more than two sentences." (from `_response_sentence_rule`)
- `response_cap`: "Maximum 20 words." (from `_response_cap_rule`)

For most emotions these conflict. A 2-sentence response at 20 words means 10 words per sentence — shorter than a natural spoken sentence. The LLM gets confused and produces inconsistent lengths. During CONSIDERING, the cap is 30 words but 2 sentences would allow ~15 words each, which is fine. During DOOR_OPEN the cap is 10 words but the sentence rule allows 1 sentence — these two happen to agree, but only by coincidence.

**File:** `conversation_orchestrator.py` → `PromptBuilder`

**What to Build:**

Remove the word-count `response_cap` from Layer 1 entirely. The sentence rule already constrains length. Replace with a spoken-language framing:

```python
def _response_cap_rule(self, canonical_stage: str) -> str:
    if canonical_stage in {"DOOR_OPEN", "ENDED"}:
        return "Speak briefly — one short phrase, the way you'd actually answer your door."
    if canonical_stage in {"CONSIDERING", "CLOSE_WINDOW", "RECOVERY"}:
        return "You may think out loud briefly before answering."
    return ""  # sentence_rule handles length elsewhere

def _response_sentence_rule(self, behavior_directives: BehaviorDirectives | None) -> str:
    if behavior_directives is None:
        return "Respond in one sentence only. Keep it natural and spoken, not formal."
    if behavior_directives.sentence_length == "short":
        return "Respond in one sentence only. Keep it natural and spoken, not formal."
    if behavior_directives.sentence_length == "medium":
        return "Respond in one or two spoken sentences. No more."
    return "Respond in two to three spoken sentences. No more."
```

The `_hard_rule_sentence` method (used in Layer 1 pre-rule) should be updated to match.

**Why "spoken, not formal":** Without this qualifier, LLMs write grammatically correct but stilted responses ("I would need to consider the monthly cost implications"). The explicit framing nudges toward "I'd have to think about it — what's the monthly price?" which is what a real person says.

**Acceptance Criteria:**
- `_response_cap_rule` no longer returns a word count ("Maximum N words") for any stage
- Layer 1 no longer contains two separate length constraints
- `_response_sentence_rule` includes the phrase "natural and spoken" or equivalent
- Existing tests that check for "Maximum" in prompt strings should be updated or removed

---

### H-03: Transcript Normalization — Phonetic Correction Layer

**Problem:** The `TranscriptNormalizationService` uses fuzzy character matching (SequenceMatcher ratio ≥ 0.8) to correct domain terms. This catches typos and mishearing of written words, but not phonetic confusions where Deepgram produces a completely different word that sounds similar. Common examples in the pest control D2D domain:

| Deepgram produces | Should be |
|---|---|
| "or kin" | "Orkin" |
| "termite" (singular) | "termites" (normalized) |
| "pick control" | "pest control" |
| "arrow sol" | "aerosol" |
| "ante" / "aunty" | "ant" / "ants" |
| "road" (misheard) | "rodent" (context-dependent) |
| "the Joneses" → "the Johnson's" | (STT common confusion) |

SequenceMatcher ratio between "or kin" and "Orkin" is only 0.67 — below the 0.8 threshold. These confusions are invisible to the current system and cause signal detection to fail (SOCIAL_PROOF_PHRASES, RAPPORT_PHRASES won't fire on garbled text).

**File:** `transcript_normalization_service.py`

**What to Build:**

Add a `PHONETIC_CORRECTION_TABLE` as a module-level constant — a flat dict of common STT errors to their canonical forms. Apply it as a pre-pass before fuzzy matching:

```python
PHONETIC_CORRECTION_TABLE: dict[str, str] = {
    "or kin": "Orkin",
    "orkin's": "Orkin",
    "pick control": "pest control",
    "pick controlled": "pest control",
    "arrow sol": "aerosol",
    "arrow sols": "aerosols",
    "ante": "ant",
    "aunty": "ant",
    "the ante": "the ant",
    "termite inspection": "termite inspection",  # preserve as-is
    "road ant": "rodent",
    "road ants": "rodents",
    "the road": "the rodent",
    "home warning": "home warranty",
    "free in spec shin": "free inspection",
    "free inspect shin": "free inspection",
    "in spec shun": "inspection",
    "ex terminator": "exterminator",
    "ex terminate": "exterminate",
    "service agreement": "service agreement",  # preserve
    "serve is": "service",
}

def _apply_phonetic_corrections(self, text: str) -> str:
    result = text
    # Case-insensitive whole-phrase replacement, preserving case of surrounding text
    for wrong, correct in PHONETIC_CORRECTION_TABLE.items():
        pattern = re.compile(r"\b" + re.escape(wrong) + r"\b", re.IGNORECASE)
        result = pattern.sub(correct, result)
    return result
```

Call `_apply_phonetic_corrections` before `_apply_fuzzy_term_corrections` in `normalize()`.

Also: lower the fuzzy match threshold for org-specific terms (company name, product names) from 0.8 to 0.75. These are the most important terms to get right and they're short words where 0.8 is too strict.

**Acceptance Criteria:**
- "or kin" in input → "Orkin" in output
- "pick control" → "pest control"
- "free in spec shin" → "free inspection"
- Phonetic corrections applied before fuzzy pass, not after
- Correction is case-insensitive (input "Or Kin" also corrects)
- `test_transcript_normalization_service.py` has a test for at least 5 of the phonetic cases

---

### H-04: Stage Transition Guard — No Premature Jumps

**Problem:** `_stage_from_analysis` maps `stage_intent` directly to stages without enforcing sequence. A rep could jump from `door_knock` → `close_attempt` in a single turn if their first utterance includes close language. The homeowner would get CLOSE_WINDOW stage guidance before even hearing the pitch, which is incoherent.

**File:** `conversation_orchestrator.py` → `_stage_from_analysis`

**What to Build:**

Add a stage advancement guard that enforces minimum progression. Use the stage sequence list (already available as `context.scenario_snapshot.stages`) to check that a stage jump doesn't skip required predecessors:

```python
STAGE_MINIMUM_PREDECESSORS: dict[str, set[str]] = {
    # Cannot enter objection_handling until pitch has started
    "objection_handling": {"initial_pitch", "pitch", "listen"},
    # Cannot enter considering until at least one objection_handling turn happened
    "considering": {"objection_handling"},
    # Cannot enter close_attempt until considering or objection_handling happened
    "close_attempt": {"objection_handling", "considering"},
}

def _guard_stage_transition(
    self,
    *,
    requested_stage: str,
    current_stage: str,
    visited_stages: set[str],
    stages: list[str],
) -> str:
    required = STAGE_MINIMUM_PREDECESSORS.get(requested_stage, set())
    if required and not required.intersection(visited_stages):
        # Find the next valid stage in the sequence instead
        current_index = next(
            (i for i, s in enumerate(stages) if s == current_stage), 0
        )
        return stages[min(current_index + 1, len(stages) - 1)]
    return requested_stage
```

Add `visited_stages: set[str] = field(default_factory=set)` to `ConversationState`. Update it on every stage change.

Call `_guard_stage_transition` as the final step in `_stage_from_analysis` before returning.

**Acceptance Criteria:**
- A rep whose first turn contains "sign today" gets pushed to `initial_pitch`, not `close_attempt`
- After visiting `initial_pitch`, the stage can advance to `objection_handling`
- `visited_stages` accumulates correctly as the session progresses
- Recovery stage is exempt from the guard (it's a transient state, not a sequence step)
- `test_conversation_orchestrator.py` has a test: single close-pressure turn from DOOR_OPEN stage → stage is NOT close_attempt

---

### H-05: Adaptive Training Skill Name Mapping — Explicit Canonicalization

**Problem:** `adaptive_training_service.py` uses skill names `["opening", "rapport", "pitch_clarity", "objection_handling", "closing"]` but grading uses `["opening", "pitch_delivery", "objection_handling", "closing_technique", "professionalism"]`. The mapping currently lives as implicit arithmetic on lines 284-300 (`_build_skill_profile`). If grading key names ever change, the adaptive service silently breaks with no error.

This is a fragile implicit coupling. The mapping should be an explicit constant.

**File:** `adaptive_training_service.py`

**What to Build:**

Add `GRADING_KEY_TO_SKILL` as a module-level constant that makes the mapping explicit:

```python
# Maps grading category keys → adaptive training skill names
GRADING_KEY_TO_SKILL: dict[str, str] = {
    "opening":            "opening",
    "pitch_delivery":     "pitch_clarity",
    "objection_handling": "objection_handling",
    "closing_technique":  "closing",
    "professionalism":    "rapport",   # professionalism is the surface form of rapport
}
```

Update `_build_skill_profile` to use `GRADING_KEY_TO_SKILL` for all lookups instead of hardcoded string keys:

```python
def _bounded_score(self, category_scores: dict, grading_key: str, fallback: float) -> float:
    skill_key = GRADING_KEY_TO_SKILL.get(grading_key, grading_key)
    raw = category_scores.get(grading_key) or category_scores.get(skill_key)
    # ... rest of existing logic
```

Also add a startup assertion (or a test) that validates `GRADING_KEY_TO_SKILL` keys match `CATEGORY_KEYS` from `grading_service.py`:

```python
# In tests/test_adaptive_training.py:
def test_grading_key_to_skill_covers_all_grading_categories():
    from app.services.adaptive_training_service import GRADING_KEY_TO_SKILL
    from app.services.grading_service import CATEGORY_KEYS
    assert set(GRADING_KEY_TO_SKILL.keys()) == set(CATEGORY_KEYS)
```

**Acceptance Criteria:**
- `GRADING_KEY_TO_SKILL` constant exists at module level in `adaptive_training_service.py`
- All category key lookups in `_build_skill_profile` go through `GRADING_KEY_TO_SKILL`
- `test_adaptive_training.py` test verifies the mapping covers all `CATEGORY_KEYS`
- If `CATEGORY_KEYS` in grading_service ever changes, the test fails loudly

---

## Implementation Notes

### Priority Order

1. **H-05** — 15-minute fix, prevents silent scoring mismatch in adaptive training. Lowest risk.
2. **H-03** — Phonetic correction table. Self-contained, no downstream effects. Add 5+ test cases.
3. **H-02** — Response cap deconfliction. Prompt-only change. Update any tests checking for "Maximum N words".
4. **H-01** — Monologue detection. New state field + reaction_intent override. Write the test alongside.
5. **H-04** — Stage transition guard. Requires new `visited_stages` state field. Highest complexity.

### Files Touched

| Feature | Primary File | Secondary |
|---|---|---|
| H-01 Monologue | `conversation_orchestrator.py` | `ConversationState` dataclass |
| H-02 Cap deconfliction | `conversation_orchestrator.py` → `PromptBuilder` | — |
| H-03 Phonetic corrections | `transcript_normalization_service.py` | `test_transcript_normalization_service.py` |
| H-04 Stage guard | `conversation_orchestrator.py` → `_stage_from_analysis` | `ConversationState` dataclass |
| H-05 Skill mapping | `adaptive_training_service.py` | `test_adaptive_training.py` |

### Do Not Change

- `CATEGORY_KEYS` order or values in `grading_service.py` — changing these breaks historical data
- `SKILL_ORDER` in `adaptive_training_service.py` — used in the manager dashboard skill graph display
- The `TranscriptNormalizationResult` dataclass shape
- The `_stage_from_analysis` return type or caller signature
