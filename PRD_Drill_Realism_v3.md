# PRD: DoorDrill Drill Quality — Phase 3
**For:** Codex
**Owner:** Cale
**Status:** Ready for Implementation
**Depends on:** PRD_Drill_Realism_v2.md (assume all Phase 2 features are implemented)

---

## Background & Goal

Phase 2 fixed the deterministic orchestration layer — emotion momentum, friction memory, interruption escalation, first-turn contracts. The homeowner now *decides* the right things. Phase 3 focuses on three separate quality layers that Phase 2 didn't touch:

1. **How the homeowner sounds** — MicroBehaviorEngine vocabulary is too thin; reps hear the same 3 fillers and 3 interruptions on repeat
2. **How the grader scores** — Grading ignores difficulty; a rep who earned a warmup from a hostile difficulty-5 persona gets the same score as one who coasted through difficulty-1
3. **What the rep learns after** — Post-session feedback is category scores; reps need to know *which specific turn* killed the conversation and why

These are independent changes. Implement them in the order listed.

---

## Feature Specs

---

### G-01: MicroBehaviorEngine — Variant Depth & Emotion Vocabulary

**Problem:** `HESITATION_VARIANTS`, `FILLER_VARIANTS`, and `INTERRUPTION_VARIANTS` each have 3 options per emotion. After 2–3 drills a rep memorizes all of them. The homeowner stops sounding spontaneous.

**File:** `backend/app/services/micro_behavior_engine.py`

**What to Build:**

Replace the current thin tuples with expanded pools. Each emotion needs at least 6–8 options across two registers (mild and strong), so the `_pick_variant` hash spreads naturally.

```python
HESITATION_VARIANTS = {
    "neutral": (
        "Uh...", "Well...", "Hmm...", "I mean...", "Let me think...",
        "Okay...", "So...", "Right...",
    ),
    "skeptical": (
        "Uh...", "Well...", "I mean...", "Hm.", "Look...",
        "I don't know...", "Right, so...", "Okay but...",
    ),
    "curious": (
        "Hmm...", "Well...", "So...", "Interesting...",
        "Oh, okay...", "Wait, so...", "Huh...", "Tell me...",
    ),
    "interested": (
        "Okay...", "Well...", "So...", "Right...",
        "Got it...", "Alright...", "Yeah...", "And...",
    ),
    "annoyed": (
        "Look...", "Okay so...", "I mean...", "Yeah, I heard you...",
    ),
}

FILLER_VARIANTS = {
    "neutral":    ("you know", "I mean", "like", "sort of", "kind of"),
    "skeptical":  ("I mean", "you know", "honestly", "look"),
    "curious":    ("you know", "like", "actually", "I guess", "kind of"),
    "interested": ("I mean", "you know", "right", "exactly", "yeah"),
    "annoyed":    ("look", "I mean", "honestly"),
}

INTERRUPTION_VARIANTS = {
    "annoyed": (
        "Hold on,", "Wait,", "Look,", "Okay, stop —",
        "Let me jump in here —", "Actually,", "No, hang on —",
    ),
    "hostile": (
        "No, hold on,", "Sorry, let me stop you there,", "Wait a second,",
        "No — stop.", "I'm going to cut you off,", "Okay, I've heard enough —",
        "That's not — listen,",
    ),
}
```

Also add two new variant types that don't exist yet:

**Trailing-off variants** — for `skeptical` and `considering` states, the homeowner doesn't always finish the sentence. Gives the feel of mulling it over:

```python
TRAILING_OFF_VARIANTS = {
    "skeptical": (
        "I just don't know...",
        "It's just that...",
        "I'd have to think about it...",
        "I mean, maybe...",
    ),
    "considering": (
        "I guess the thing is...",
        "It's just...",
        "I'm not sure, it's...",
        "Maybe, I just...",
    ),
}
```

Inject trailing-off text at end of response when `sentence_length == "medium"` and `emotion_after in {"skeptical", "considering"}` and a coin-flip (seeded by session hash) comes up. Rate: ~30% of turns.

**Acceptance Criteria:**
- Each emotion has at least 6 hesitation and 5 filler options
- Interruption variants: at least 7 for `annoyed`, at least 7 for `hostile`
- Trailing-off fires on ~30% of skeptical/considering medium-length turns
- In a 10-turn drill, the same hesitation opener should not appear more than twice (`_remember` window expands from 2 to 4)

---

### G-02: Emotion-Specific Pause Profiles

**Problem:** Pause timings in `_pause_before_ms` and `_pause_after_ms` are based on tone only. Emotion affects natural pause rhythm — a `hostile` homeowner cuts in fast with no pause; an `interested` homeowner pauses longer before responding (thinking it over). Currently both get similar pauses.

**File:** `backend/app/services/micro_behavior_engine.py`

**What to Build:**

Add `PAUSE_BY_EMOTION` and use it to adjust the base pause in `_pause_before_ms`:

```python
PAUSE_BEFORE_OFFSET_BY_EMOTION = {
    "hostile":    -80,   # snaps back — no thinking pause
    "annoyed":    -40,
    "neutral":      0,
    "skeptical":  +60,   # has to decide how guarded to be
    "curious":   +120,   # genuinely thinking about what was said
    "interested": +160,  # warmest, most deliberate
}
```

Apply as: `return max(40, base_pause + PAUSE_BEFORE_OFFSET_BY_EMOTION.get(emotion_after, 0))`

**Acceptance Criteria:**
- `hostile` homeowner opening pause is < 100ms
- `interested` homeowner opening pause is > 400ms
- `skeptical` homeowner opening pause is 300–450ms range
- Existing pause tests should still pass (adjust expected values if needed)

---

### G-03: CONSIDERING and CLOSE_WINDOW Stage Guidance Depth

**Problem:** Both stages have 1-sentence instructions. These are the highest-stakes moments of the conversation — where the rep either earns the booking or blows it — and the homeowner gets almost no behavioral direction.

**File:** `backend/app/services/conversation_orchestrator.py` → `PromptBuilder.STAGE_GUIDANCE`

**What to Build:**

```python
"CONSIDERING": (
    "You are not sold, but you have not walked away either. Something the rep said opened a small crack. "
    "Behave like a real person who is genuinely undecided: ask a clarifying question, stall with 'I'd have to think about it', "
    "or float a soft objection that isn't a hard no. "
    "Do NOT cave just because the rep asked nicely. The rep still needs to answer the specific thing that's holding you back. "
    "Common realistic responses at this stage: 'What does the monthly cost actually look like?', "
    "'I'd want to run it by my wife first.', 'How long have you guys been operating around here?', "
    "'I mean, maybe — what would the process look like?' "
    "Only warm up further if the rep gives a concrete, credible answer to your last question. "
    "A vague or pushy answer should snap you back toward skeptical."
),
"CLOSE_WINDOW": (
    "The rep is trying to close. You need a real reason to say yes — not enthusiasm, not pressure. "
    "Default to a soft decline or a deferral unless the rep has genuinely earned your trust: "
    "'Let me think about it.', 'I'll talk to my wife and we'll reach out.', 'Not today, but maybe.' "
    "If the rep is using urgency pressure ('only today', 'right now'), resist harder — real homeowners hate that. "
    "The only things that can move you to yes at this stage: "
    "  (1) All your major objections have been addressed specifically, not generically. "
    "  (2) The rep has been calm, credible, and non-pushy throughout. "
    "  (3) The ask is low-friction (free inspection, quick look, not 'sign now'). "
    "If all three are true, it's realistic to agree to a low-commitment next step. "
    "If one or more is missing, give a polite but firm deferral and don't reopen it."
),
```

Also add a new stage that currently has no guidance at all:

```python
"RECOVERY": (
    "The rep just did something that de-escalated the conversation after a difficult moment — "
    "they acknowledged your concern, backed off pressure, or gave a specific credible answer. "
    "React to that. Don't immediately forgive everything, but show that you noticed: "
    "'Okay, that's actually a fair point.', 'Alright, I can hear that.', 'That makes more sense.' "
    "You are not fully back onside yet — stay slightly guarded — but the tone softens measurably. "
    "Do not raise a new objection this turn unless the rep's recovery was unconvincing."
),
```

Wire `RECOVERY` into `INTERNAL_STAGE_MAP` triggered when `emotion_momentum >= 2` and previous emotion was `annoyed` or `hostile`.

**Acceptance Criteria:**
- CONSIDERING and CLOSE_WINDOW guidance fills at least 4 sentences with specific behavioral examples
- RECOVERY stage is triggered correctly based on momentum threshold and shows in the system prompt
- A rep who earns recovery should see measurably softer homeowner language on that turn

---

### G-04: Difficulty-Aware Grading

**Problem:** `GradingService` sends a transcript to the LLM with category weights (15/25/30/20/10) but no context about homeowner difficulty, emotion trajectory, or how hard the rep had to work. A rep who won over a hostile difficulty-5 persona scores the same as one who coasted a difficulty-1.

**File:** `backend/app/services/grading_service.py` → `GradingPromptBuilder.build()`

**What to Build:**

Add a `session_context` parameter to `GradingPromptBuilder.build()` that accepts a dict with:
- `difficulty: int` (1–5)
- `emotion_trajectory: list[str]` (ordered list of homeowner emotions across turns)
- `peak_resistance: int` (max objection_pressure reached)
- `objections_resolved: list[str]`
- `total_rep_turns: int`

Inject this as a grading modifier block in the prompt:

```python
DIFFICULTY_LABEL = {1: "easy", 2: "moderate", 3: "challenging", 4: "hard", 5: "very hard"}

def _build_session_context_block(self, session_context: dict) -> str:
    difficulty = session_context.get("difficulty", 1)
    trajectory = session_context.get("emotion_trajectory", [])
    peak = session_context.get("peak_resistance", 0)
    resolved = session_context.get("objections_resolved", [])
    turns = session_context.get("total_rep_turns", 0)

    label = DIFFICULTY_LABEL.get(difficulty, "unknown")
    trajectory_str = " → ".join(trajectory) if trajectory else "unknown"
    resolved_str = ", ".join(resolved) if resolved else "none"

    return (
        f"SESSION CONTEXT (use this to calibrate scores):\n"
        f"- Scenario difficulty: {difficulty}/5 ({label})\n"
        f"- Homeowner emotion trajectory: {trajectory_str}\n"
        f"- Peak resistance level reached: {peak}/5\n"
        f"- Objections resolved by rep: {resolved_str}\n"
        f"- Total rep turns: {turns}\n"
        f"Adjust scores upward if the rep achieved good outcomes against high resistance. "
        f"A rep who moved the homeowner from hostile to curious on difficulty 4 deserves more credit "
        f"on objection_handling than a rep who got the same outcome on difficulty 1. "
        f"Specifically: if peak_resistance >= 4, weight objection_handling evidence more heavily. "
        f"If emotion_trajectory shows a recovery arc (hostile/annoyed → neutral/curious), "
        f"call that out as a highlight."
    )
```

Also update `_build_opening_weight_modifier` (see G-05 below) to fire here.

Wire `session_context` into `GradingService.grade_session()` using data already captured in `TurnCommitContext` and `ConversationState`.

**Acceptance Criteria:**
- Grading prompt includes SESSION CONTEXT block when session_context is provided
- `GradingService.grade_session()` passes difficulty, trajectory, and peak_resistance from session artifacts
- A session with `difficulty=5` and a hostile→curious arc produces a visible highlight about the recovery in the scorecard
- Grading output schema is unchanged (no new fields required)

---

### G-05: Opening Quality Modifier on Downstream Scores

**Problem:** The grader weights `opening` at 15%, but a bad opening creates the conditions for a bad rest of the conversation. If the rep's first turn generates `pushes_close` or `neutral_delivery`, the homeowner starts guarded — and the rep's objection handling and closing scores suffer for it. The grader doesn't know this chain exists.

**File:** `backend/app/services/grading_service.py`

**What to Build:**

Add an opening quality assessment to the grading prompt. Pull the behavioral signals from the first rep turn (turn index 0 or 1) out of `TurnCommitContext` and pass them in:

```python
OPENING_SIGNAL_LABELS = {
    "builds_rapport":    "strong opener",
    "mentions_social_proof": "strong opener",
    "explains_value":    "neutral opener",
    "neutral_delivery":  "weak opener",
    "pushes_close":      "damaging opener",
    "dismisses_concern": "damaging opener",
}

def _build_opening_modifier(self, first_turn_signals: list[str]) -> str:
    labels = [OPENING_SIGNAL_LABELS[s] for s in first_turn_signals if s in OPENING_SIGNAL_LABELS]
    if not labels:
        return ""
    strongest = "damaging opener" if "damaging opener" in labels else (
        "weak opener" if "weak opener" in labels else (
        "strong opener" if "strong opener" in labels else "neutral opener"
    ))
    return (
        f"OPENING QUALITY: {strongest} (signals: {', '.join(first_turn_signals)}).\n"
        + (
            "The rep's opening created unnecessary resistance. "
            "When scoring objection_handling and closing_technique, note that the rep "
            "was working against resistance they created — factor that into your rationale."
            if strongest == "damaging opener" else ""
        )
        + (
            "The rep opened well, which likely made subsequent stages easier. "
            "Weight their early rapport positively in professionalism."
            if strongest == "strong opener" else ""
        )
    )
```

**Acceptance Criteria:**
- A session where turn 1 has `pushes_close` produces a grading prompt that includes "damaging opener" language
- A session where turn 1 has `builds_rapport` + `mentions_social_proof` produces "strong opener" language
- The modifier is visible in the grading rationale for `professionalism` and `opening` categories

---

### G-06: Post-Session Inflection Point Analysis

**Problem:** After a session, reps see category scores and an `ai_summary`. They don't know *which specific turn* is where they lost the homeowner, or what they should have said instead. This is the highest-value coaching output the product could give.

**File:** New service `backend/app/services/inflection_point_service.py`

**What to Build:**

An `InflectionPointService` that analyzes the `TurnCommitContext` sequence from `ReconstructedTimeline` and identifies 1–3 inflection turns: moments where the homeowner's trajectory changed significantly (positive or negative).

```python
@dataclass
class InflectionPoint:
    turn_index: int
    rep_turn_id: str
    ai_turn_id: str
    direction: str           # "positive" | "negative"
    emotion_before: str
    emotion_after: str
    pressure_before: int
    pressure_after: int
    behavioral_signals: list[str]
    coaching_label: str      # e.g. "Lost them here", "Turned it around"
    coaching_note: str       # 1-sentence explanation

class InflectionPointService:
    def analyze(self, timeline: ReconstructedTimeline) -> list[InflectionPoint]:
        points = []
        for ctx in timeline.turn_contexts:
            delta = self._compute_delta(ctx)
            if abs(delta) >= 2:
                points.append(self._build_inflection(ctx, delta))
        # Sort by abs delta, return top 3
        return sorted(points, key=lambda p: abs(p.pressure_after - p.pressure_before), reverse=True)[:3]

    def _compute_delta(self, ctx: TurnCommitContext) -> int:
        emotion_delta = EMOTION_ORDER.index(ctx.emotion_after) - EMOTION_ORDER.index(ctx.emotion_before)
        pressure_delta = (ctx.pressure_after or 0) - (ctx.pressure_before or 0)
        return emotion_delta + pressure_delta

    def _build_inflection(self, ctx: TurnCommitContext, delta: int) -> InflectionPoint:
        direction = "negative" if delta > 0 else "positive"
        coaching_label = "Lost them here" if direction == "negative" else "Turned it around"
        coaching_note = self._generate_coaching_note(ctx, direction)
        return InflectionPoint(
            turn_index=...,
            rep_turn_id=ctx.rep_turn_id or "",
            ai_turn_id=ctx.ai_turn_id or "",
            direction=direction,
            emotion_before=ctx.emotion_before or "unknown",
            emotion_after=ctx.emotion_after or "unknown",
            pressure_before=ctx.pressure_before or 0,
            pressure_after=ctx.pressure_after or 0,
            behavioral_signals=list(ctx.behavioral_signals),
            coaching_label=coaching_label,
            coaching_note=coaching_note,
        )
```

`_generate_coaching_note` uses a lookup table, not an LLM call — it must be fast and synchronous:

```python
INFLECTION_COACHING_NOTES = {
    # (direction, signal) → note
    ("negative", "pushes_close"):      "Rep pushed for a close before earning trust — homeowner hardened.",
    ("negative", "dismisses_concern"): "Rep brushed off the homeowner's concern — caused immediate resistance.",
    ("negative", "ignores_objection"): "Rep dodged the active objection — homeowner noticed and pushed back harder.",
    ("negative", "neutral_delivery"):  "Rep gave a generic answer when the homeowner needed something specific.",
    ("positive", "acknowledges_concern"): "Rep acknowledged the concern directly — broke the resistance.",
    ("positive", "provides_proof"):    "Rep backed up a claim — homeowner's skepticism dropped.",
    ("positive", "reduces_pressure"):  "Rep took pressure off — homeowner opened up.",
    ("positive", "mentions_social_proof"): "Rep's neighbor reference landed — homeowner became curious.",
}
```

Surface `InflectionPoint` results in the `SessionArtifact` as a new `inflection_points` artifact type. Wire into `session_postprocess_service.py`.

**Acceptance Criteria:**
- `InflectionPointService.analyze()` returns 0–3 inflection points per session
- Negative inflection: identified when emotion moves 1+ steps negative AND pressure increases ≥ 2
- Positive inflection: identified when pressure drops ≥ 2 OR emotion moves 2+ steps positive
- Coaching notes are generated from the lookup table without LLM calls
- Inflection points are stored as a `session_artifact` with `artifact_type = "inflection_points"`
- No new API endpoints required — existing artifact retrieval handles it

---

### G-07: Inflection Points in Post-Session Scorecard

**Problem:** Even if `InflectionPointService` runs, the output is buried in artifacts. Reps look at the scorecard — that's the surface they actually see.

**File:** `backend/app/services/grading_service.py`

**What to Build:**

After computing inflection points in post-process, pass them into the grading prompt as an additional context block:

```python
def _build_inflection_block(self, inflection_points: list[dict]) -> str:
    if not inflection_points:
        return ""
    lines = ["KEY MOMENTS IN THIS SESSION (use as evidence in your rationale):"]
    for pt in inflection_points:
        label = pt.get("coaching_label", "")
        note = pt.get("coaching_note", "")
        direction = pt.get("direction", "")
        turn = pt.get("turn_index", "?")
        lines.append(f"  - Turn {turn} [{direction.upper()}]: {label}. {note}")
    lines.append(
        "Reference these moments in your highlights and rationale. "
        "If there is a clear 'Lost them here' moment, it should appear as an 'improve' highlight."
    )
    return "\n".join(lines)
```

**Acceptance Criteria:**
- Scorecard `ai_summary` references the specific turn index for a negative inflection point when one exists
- An `improve` highlight is generated for each `negative` inflection point (up to 2)
- A `strong` highlight is generated for `positive` inflection points where `direction == "positive"` and `emotion_after in {"curious", "interested"}`

---

## Implementation Notes for Codex

### File Targets

| Feature | Primary File | New Files |
|---|---|---|
| G-01 Variant depth | `micro_behavior_engine.py` | — |
| G-02 Pause profiles | `micro_behavior_engine.py` | — |
| G-03 Stage guidance depth | `conversation_orchestrator.py` → `PromptBuilder` | — |
| G-04 Difficulty-aware grading | `grading_service.py` | — |
| G-05 Opening quality modifier | `grading_service.py` | — |
| G-06 Inflection point service | `session_postprocess_service.py` | `inflection_point_service.py` |
| G-07 Inflection points in scorecard | `grading_service.py` | — |

### Priority Order

1. **G-01 + G-02** together — both in `micro_behavior_engine.py`, ship as one PR
2. **G-03** — Stage guidance rewrite, isolated change in `PromptBuilder`
3. **G-06** — New service, no dependency on G-04/G-05
4. **G-04 + G-05 + G-07** together — all in `grading_service.py`, ship as one PR

### Existing Tests to Keep Green

- `test_micro_behavior_engine.py` — pause timings will change with G-02; update expected values
- `test_microbehavior_prompt_integration.py` — variant pool tests; update to check for ≥6 options
- `test_grading_engine_v2.py` — grading prompt shape; add assertions for SESSION CONTEXT block
- `test_edge_case_behaviors.py` — RECOVERY stage trigger

### Do Not Change

- `MicroBehaviorPlan` and `MicroBehaviorSegment` dataclass shapes (mobile may read these)
- `StructuredScorecardPayloadV2` schema (adding context to the prompt is fine; changing the output schema is not)
- `SessionArtifact` artifact_type enum if it's database-backed — add `"inflection_points"` as a new value, don't modify existing ones

---

## Success Metrics

After G-01/G-02: Same rep, same scenario — two back-to-back drills should produce noticeably different homeowner phrasing on at least 4 out of 8 turns.

After G-03: A rep who earns CONSIDERING should feel the homeowner genuinely wrestling with the decision, not just waiting to say no.

After G-04/G-05: A rep who scores 72 on difficulty-1 should score higher than a rep who scores 68 on difficulty-5 after calibration is applied.

After G-06/G-07: A rep should be able to read their scorecard and identify the exact turn where they lost the homeowner, with a one-sentence explanation.
