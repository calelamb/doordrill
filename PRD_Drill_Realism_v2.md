# PRD: DoorDrill Homeowner Realism — Phase 2
**For:** Codex
**Owner:** Cale
**Status:** Ready for Implementation
**Priority:** P0 — Core product quality

---

## Background & Goal

DoorDrill trains door-to-door sales reps by simulating realistic homeowner conversations. The homeowner AI must react the way a real person would — picking up on specific claims, carrying emotional momentum, escalating naturally when ignored, and softening when the rep earns it.

Recent improvements (commit 7c5cba9) fixed the most glaring issue: the homeowner was ignoring social proof mentions and responding to "hey how's it going" with a hostile interrogation. Those are committed. This PRD defines the next wave.

**North star:** Every rep utterance should produce a homeowner response that could plausibly have come from a real person standing in their doorway. If a transcript sounds like a chatbot or an NPC, we have failed.

---

## What's Already in Place (Don't Duplicate)

- `ConversationTurnAnalyzer` → `TurnAnalysis` → `HomeownerResponsePlan` pipeline
- `STAGE_GUIDANCE` dict with per-stage behavioral instructions
- `reaction_intent` field (free-form directive for this turn's goal)
- `homeowner_posture` field (dynamic stance label)
- `PersonaRealismPack` (disclosure_style, interruption_tolerance, skepticism_threshold, softening_speed, willingness_to_book, detail_preference)
- `HELPFUL_SIGNALS` / `HARMFUL_SIGNALS` detection
- `SOCIAL_PROOF_PHRASES` + `mentions_social_proof` signal (new)
- `RAPPORT_PHRASES` expansion (new)
- `ignored_objection_streak` counter
- `objection_wording_cursor` for variant rotation
- `ConversationRealismEvalService` scoring (directness, objection_carryover, emotional_consistency, closing_resistance)
- Objection resolution progress tracking (0–4 scale per objection)

---

## Feature Specs

---

### F-01: Emotion Momentum Dampening (Rep Redemption Arc)

**Problem:** The emotion state currently snaps between levels based on a single turn. A rep who was hostile and then apologizes can recover in one message. Real homeowners don't instantly forgive — they stay guarded for a beat.

**What to Build:**

Add an `emotion_momentum` counter to `ConversationState` (integer, range -3 to +3). When emotion changes direction (e.g., annoyed → neutral), hold the transition for 1–2 turns unless the signal is very strong (e.g., explicit acknowledgement + low-pressure + personalization all firing at once).

```
Proposed field:
  emotion_momentum: int = 0  # positive = warming, negative = cooling

Logic (inside _plan_next_state):
  - On each turn, compute delta (helpful_count - harmful_count)
  - If delta > 0: increment emotion_momentum by 1 (max 3)
  - If delta < 0: decrement emotion_momentum by 1 (min -3)
  - Only allow upward emotion transition if emotion_momentum >= 2
  - Allow downward emotion transition freely (homeowners sour faster than they warm)
  - Exception: if rep uses PRESSURE_PHRASES while homeowner is already annoyed,
    allow immediate skip to hostile regardless of momentum
```

**Acceptance Criteria:**
- A rep who does one good thing after three bad turns takes at least 2 more good turns to move from `annoyed` to `neutral`
- A rep who is genuinely excellent (3+ helpful signals in one turn) can still get a one-turn recovery
- Downward transitions (good → bad) remain immediate

---

### F-02: Friction Memory — No Plateau After Good Turn

**Problem:** `friction_level` in `HomeownerResponsePlan` is computed fresh each turn. A rep who builds rapport and then goes silent for 3 turns experiences the same friction as if they'd been consistently excellent. The homeowner has no memory of the plateau.

**What to Build:**

Add `turns_since_positive_signal: int = 0` to `ConversationState`. Increment it each turn where no HELPFUL_SIGNALS fire. Reset to 0 when at least one HELPFUL_SIGNAL fires. When computing `friction_level`, add `min(2, turns_since_positive_signal // 2)` to the base friction score.

```
Effect:
  - Rep who was doing great but then stalls: friction slowly rises back
  - Rep who is consistently helpful: friction stays low
  - This simulates: "You were great for a sec, but now I feel like a mark again"
```

**Acceptance Criteria:**
- After 4+ turns with no helpful signals, friction should be at least 1 level higher than at the beginning of the stall
- Friction does not compound unboundedly — cap the plateau penalty at +2

---

### F-03: Semantic Anchor Validation Against Stance

**Problem:** `HomeownerResponsePlan.semantic_anchors` defines what topics the homeowner's response should stay anchored to. But there's no check that those anchors are compatible with the current `stance`. A homeowner in `aggressive_pushback` stance might be assigned a "curious about pricing" anchor, causing the LLM to produce a schizophrenic response.

**What to Build:**

Add a validation step inside `_plan_next_response` that filters `semantic_anchors` against the current `stance`:

```python
STANCE_ANCHOR_BLOCKLIST = {
    "aggressive_pushback": {"curious", "interested in", "open to"},
    "warming": {"skeptical of", "doubts", "refuses"},
    "resigned": {"still fighting", "raising new objections"},
}

def _validate_anchors(anchors: list[str], stance: str) -> list[str]:
    blocked = STANCE_ANCHOR_BLOCKLIST.get(stance, set())
    return [a for a in anchors if not any(b in a.lower() for b in blocked)]
```

**Acceptance Criteria:**
- A homeowner in `aggressive_pushback` stance never gets an anchor containing "curious" or "interested"
- A homeowner in `warming` stance never gets an anchor that implies they're still stonewalling

---

### F-04: Interruption Escalation Model

**Problem:** `ignored_objection_streak` exists but only triggers the `ignored_objection_wall` edge case directive after an unspecified threshold. There's no clear escalation sequence, and the homeowner doesn't interrupt mid-pitch realistically.

**What to Build:**

Add `interruption_count: int = 0` to `ConversationState`. Implement a 3-stage escalation model:

```
Stage 1 (ignored_objection_streak == 1):
  reaction_intent override → "The rep didn't address your last concern.
  Make a short, pointed re-raise before letting them continue."

Stage 2 (ignored_objection_streak == 2):
  reaction_intent override → "The rep has now ignored your concern twice.
  Be more insistent. Phrase it as a blocker: 'I need you to address X before we go further.'"

Stage 3 (ignored_objection_streak >= 3):
  Trigger `ignored_objection_wall` edge case.
  Set interruption_mode = True in BehaviorDirectives.
  reaction_intent override → "You are done waiting. Do not let the rep continue.
  Interrupt and tell them you're ending the conversation unless they respond to X right now."
```

Also add `interruption_mode` check to the PromptBuilder so when `interruption_mode=True`, the system prompt instructs the homeowner to cut off the rep mid-sentence if needed.

**Acceptance Criteria:**
- First ignored objection → pointed re-raise
- Second ignored objection → hard blocker stance
- Third+ ignored objection → explicit interruption language, no re-engagement unless addressed
- Resetting: `ignored_objection_streak` resets to 0 when rep addresses the objection

---

### F-05: Homeowner Fatigue After Extended Conversation

**Problem:** No concept of conversation length affecting homeowner behavior. A 20-turn conversation plays out with the same homeowner energy as a 5-turn conversation. Real people get tired, start wrapping up, check their watch.

**What to Build:**

Use `state.rep_turns` (already exists) to compute a fatigue modifier:

```python
def _fatigue_modifier(rep_turns: int) -> str | None:
    if rep_turns < 10:
        return None
    if rep_turns < 15:
        return (
            "You've been at the door for a while now. "
            "You're getting slightly fatigued — your responses get shorter and you start
            glancing back inside."
        )
    return (
        "This conversation has gone on too long. You are ready to end it. "
        "Tell the rep you need to go, but leave the door open if they've been good:
        'Look, I've got to get back inside. If you've got something to leave me with, I'll read it.'"
    )
```

Inject this into Layer 5 of the system prompt (behavioral directives) when `rep_turns >= 10`.

**Acceptance Criteria:**
- Turns 10–14: homeowner response length visibly shortens, language gets more clipped
- Turns 15+: homeowner proactively tries to wrap up the conversation
- If the rep has been consistently excellent (rapport_score >= 5), the fatigue threshold shifts to turn 18

---

### F-06: Objection Fatigue — Escalate or Resign

**Problem:** The homeowner can raise the same objection indefinitely at the same intensity. Real people either escalate ("I've told you twice already — the price is a dealbreaker, I'm done") or resign to it ("Fine, whatever, I get it, you're not going to answer that").

**What to Build:**

Add `objection_raise_count: dict[str, int]` to `ConversationState`. Increment every time an objection is surfaced in `reaction_intent` or `allowed_new_objection`.

```python
def _objection_fatigue_directive(
    objection: str,
    raise_count: int,
    emotion: str,
) -> str | None:
    if raise_count < 3:
        return None
    if emotion in ("annoyed", "hostile"):
        return (
            f"You have raised '{objection}' {raise_count} times. "
            "You are done repeating yourself. This is now a dealbreaker. "
            "Tell the rep directly: this issue must be resolved or you're done."
        )
    # Warmer emotion → resignation
    return (
        f"You have raised '{objection}' {raise_count} times and haven't gotten a satisfying answer. "
        "You are starting to accept it might just be a sticking point. "
        "Acknowledge it but don't fight as hard — maybe something else convinces you."
    )
```

**Acceptance Criteria:**
- Objection raised 3+ times by annoyed/hostile homeowner → explicitly escalated to dealbreaker
- Objection raised 3+ times by curious/neutral homeowner → de-prioritized, homeowner mentally moves on
- Objection raise count resets when objection is marked resolved

---

### F-07: Weighted Booking Gates

**Problem:** `next_step_acceptability` has four levels (not_allowed, info_only, inspection_only, booking_possible), but the gate between them is a binary check on friction_gates. In practice, homeowners transition to "willing to book" based on cumulative evidence — rapport score, objections resolved, pressure level — not a single on/off gate.

**What to Build:**

Replace the binary `friction_gates` check with a weighted score that unlocks each tier:

```python
def _compute_booking_score(state: ConversationState, persona: HomeownerPersona) -> int:
    score = 0
    score += min(3, state.rapport_score)                    # max 3
    score += len(state.resolved_objections) * 2             # 2 per resolved objection
    score -= state.objection_pressure                       # subtract raw pressure
    score -= (1 if state.emotion in ("annoyed", "hostile") else 0)
    score += (1 if persona.buy_likelihood in ("high", "medium-high") else 0)
    return score

BOOKING_SCORE_THRESHOLDS = {
    "booking_possible": 6,
    "inspection_only": 3,
    "info_only": 1,
    "not_allowed": 0,
}
```

This score-based gate means a rep who resolves 2 objections early can get to `booking_possible` faster, while a rep who accumulates pressure can be locked out even with decent rapport.

**Acceptance Criteria:**
- Resolving 3+ objections with good rapport unlocks booking in fewer turns than the current baseline
- High pressure + unresolved objections keeps the gate closed even if rapport is positive
- `buy_likelihood: low` persona requires 2 extra points across the board

---

### F-08: Posture / Friction Conflict Detection

**Problem:** `homeowner_posture` and `friction_level` can disagree. For example: posture = `warming` with friction_level = 4 sends the LLM contradictory signals and produces incoherent responses.

**What to Build:**

Add a conflict check after both are computed in `_plan_next_response`:

```python
POSTURE_FRICTION_RANGES = {
    "aggressive_pushback": (3, 5),
    "defensive": (2, 4),
    "guarded": (1, 3),
    "testing_claims": (1, 3),
    "warming": (0, 2),
    "open": (0, 1),
    "resigned": (0, 3),
}

def _resolve_posture_friction_conflict(
    posture: str,
    friction_level: int,
) -> int:
    lo, hi = POSTURE_FRICTION_RANGES.get(posture, (0, 5))
    return max(lo, min(hi, friction_level))
```

Apply this clamp before writing to `HomeownerResponsePlan`.

**Acceptance Criteria:**
- A `warming` homeowner never has friction_level above 2
- An `aggressive_pushback` homeowner never has friction_level below 3
- Logs a warning when a conflict is detected and clamped (for observability)

---

### F-09: Bidirectional Behavioral Signal Detection

**Problem:** We detect what the rep does well (HELPFUL_SIGNALS) but homeowner-side signals are missing. We don't know if the homeowner is genuinely warming, digging in, or bluffing. These homeowner signals should feed back into the rep analysis and scoring.

**What to Build:**

Add `HomeownerSignalDetector` class that analyzes the homeowner's prior response text (already in `turn_history`) for behavioral cues:

```python
HOMEOWNER_WARMING_PHRASES = (
    "okay, that makes sense",
    "i guess i could",
    "tell me more",
    "how does that work",
    "what would that look like",
    "that's fair",
)
HOMEOWNER_HARDENING_PHRASES = (
    "i told you",
    "i already said",
    "not interested",
    "please just",
    "i need to go",
    "i'm not going to",
)
HOMEOWNER_TESTING_PHRASES = (
    "what if",
    "how do i know",
    "can you prove",
    "show me",
    "what's the catch",
)
```

These signals:
1. Feed into `ConversationRealismEvalService` to validate that homeowner transitions are motivated
2. Are logged to `SessionArtifact` metadata for post-drill analytics
3. Affect `reaction_intent` on the next turn — if the homeowner was testing and the rep didn't answer the test, escalate friction

**Acceptance Criteria:**
- Homeowner warming phrases in the last turn reduce friction_level by 1 on the next turn
- Homeowner hardening phrases increase the escalation risk on the next turn
- These signals are visible in the post-drill analytics artifact

---

### F-10: `testing_claims` Posture Requires Follow-Up Enforcement

**Problem:** When `homeowner_posture == "testing_claims"`, the homeowner is supposed to push on a specific claim the rep made. But if the rep doesn't follow up on that test, the system doesn't track the miss. The homeowner just moves on.

**What to Build:**

Add `pending_test_question: str | None = None` to `ConversationState`. When posture is `testing_claims`, save the specific claim being tested. On the next rep turn, check if the rep addressed it:

```python
def _check_pending_test(
    state: ConversationState,
    referenced_concerns: list[str],
    behavioral_signals: list[str],
) -> bool:
    if not state.pending_test_question:
        return True
    # Did the rep address the test?
    test_topic_keywords = state.pending_test_question.lower().split()
    rep_text_lower = ...
    return any(kw in rep_text_lower for kw in test_topic_keywords if len(kw) > 3)
```

If the rep failed to address the test:
- Increment `ignored_objection_streak`
- Set `reaction_intent` to re-surface the test with increasing urgency

**Acceptance Criteria:**
- If homeowner asks "how do I know you're insured?" and rep ignores it, next homeowner turn must address the dodge
- The ignored test escalates on the same streak counter as ignored objections (F-04)

---

### F-11: Objection Carryover Requires Meaningful Re-Statement

**Problem:** `ConversationRealismEvalService` checks for objection carryover, but the current implementation only checks if the same objection keyword appears again. It doesn't verify that the homeowner actually made the rep work for it — the homeowner might just say "yeah, price" as a one-word re-raise, which doesn't feel earned.

**What to Build:**

Add `min_carryover_length: int = 12` check to the realism eval. An objection carryover only counts as "meaningful" if the homeowner response containing the re-raise is at least 12 words and includes at least one of the `OBJECTION_SEMANTIC_ANCHORS` for that objection type.

```python
def _score_objection_carryover(self, transcript: list[dict]) -> float:
    ...
    for turn in homeowner_turns:
        for objection in active_objections:
            if objection_keyword_in(turn["text"], objection):
                word_count = len(turn["text"].split())
                anchors_present = any(
                    anchor in turn["text"].lower()
                    for anchor in OBJECTION_SEMANTIC_ANCHORS.get(objection, ())
                )
                if word_count >= 12 and anchors_present:
                    meaningful_carryovers += 1
                else:
                    weak_carryovers += 1
    # Score weak carryovers at half value
    return (meaningful_carryovers + 0.5 * weak_carryovers) / total_expected
```

This raises the quality bar: the homeowner must actually articulate why they still have the objection, not just grunt a keyword.

**Acceptance Criteria:**
- Realism eval `objection_carryover` score distinguishes between meaningful and perfunctory re-raises
- The distinction is logged so we can analyze which objections the homeowner is lazy about carrying

---

### F-12: Persona Communication Style → Response Length + Vocabulary

**Problem:** `PersonaEnricher` computes `communication_style` (terse, chatty, confrontational, analytical) but this field is not used anywhere downstream. The homeowner always responds at the same length regardless of their persona.

**What to Build:**

Wire `communication_style` into `BehaviorDirectives.sentence_length` and `PromptBuilder` Layer 4:

```python
COMMUNICATION_STYLE_DIRECTIVES = {
    "terse": (
        "You speak in short bursts — 1–2 sentences max. "
        "You don't volunteer information. If you're curious, you ask one quick question."
    ),
    "chatty": (
        "You are a talker. You respond with 3–4 sentences and often riff on what the rep says. "
        "You might go off on a small tangent before circling back."
    ),
    "confrontational": (
        "You get right to the point, often rhetorically. "
        "You challenge statements directly: 'Prove it.' or 'That's what they all say.'"
    ),
    "analytical": (
        "You ask specific, probing questions. You want data. "
        "You pause before responding and pick apart claims methodically."
    ),
}
```

Inject the relevant directive as a permanent constraint in Layer 4 (persona personality).

**Acceptance Criteria:**
- A `terse` homeowner never produces a 4-sentence response
- A `chatty` homeowner regularly produces 3+ sentence responses
- A `confrontational` homeowner uses rhetorical challenges at least once every 2–3 turns

---

### F-13: First-Turn Naturalness Contract (DOOR_OPEN Hardening)

**Problem:** Even with the new DOOR_OPEN stage guidance, the LLM occasionally produces responses like "Can I help you?" immediately followed by an objection about price. The first turn should be pure reaction to the rep's opener — no objections, no interrogation if the rep just said hi.

**What to Build:**

Add a hard rule to the turn analysis:

```python
def _is_first_meaningful_turn(state: ConversationState) -> bool:
    return state.rep_turns <= 1

# Inside _plan_next_response:
if _is_first_meaningful_turn(state):
    response_plan.allowed_new_objection = None  # hard override
    response_plan.friction_level = min(response_plan.friction_level, 1)
    reaction_intent = (
        "This is turn 1. React ONLY to what the rep just said — nothing else. "
        "If they greeted you, greet them back naturally. "
        "If they mentioned a neighbor, react to that. "
        "No objections. No interrogation. No sales resistance. Just be a person."
    )
```

**Acceptance Criteria:**
- Turn 1 responses never include objections
- Turn 1 responses never ask "what are you selling?" unless the rep said something that implied a sales pitch
- Turn 1 friction_level is capped at 1 regardless of persona difficulty

---

## Implementation Notes for Codex

### File Targets

| Feature | Primary File | Secondary File |
|---|---|---|
| F-01 Emotion Momentum | `conversation_orchestrator.py` → `_plan_next_state` | `ConversationState` dataclass |
| F-02 Friction Memory | `conversation_orchestrator.py` → `_plan_next_response` | `ConversationState` dataclass |
| F-03 Anchor Validation | `conversation_orchestrator.py` → `_plan_next_response` | New constant `STANCE_ANCHOR_BLOCKLIST` |
| F-04 Interruption Escalation | `conversation_orchestrator.py` → `_reaction_intent` | `prompt_builder.py` Layer 5 |
| F-05 Homeowner Fatigue | `conversation_orchestrator.py` → `_plan_next_response` | `prompt_builder.py` Layer 5 |
| F-06 Objection Fatigue | `conversation_orchestrator.py` → `_reaction_intent` | `ConversationState` dataclass |
| F-07 Weighted Booking Gates | `conversation_orchestrator.py` → `_compute_next_step_acceptability` | `HomeownerResponsePlan` |
| F-08 Posture/Friction Conflict | `conversation_orchestrator.py` → `_plan_next_response` | New constant `POSTURE_FRICTION_RANGES` |
| F-09 Bidirectional Signals | New `HomeownerSignalDetector` class | `ConversationRealismEvalService` |
| F-10 Testing Claims Enforcement | `conversation_orchestrator.py` → `ConversationTurnAnalyzer.analyze` | `ConversationState` dataclass |
| F-11 Objection Carryover Quality | `realism_eval_service.py` → `_score_objection_carryover` | `OBJECTION_SEMANTIC_ANCHORS` |
| F-12 Communication Style | `conversation_orchestrator.py` → `_build_behavior_directives` | `prompt_builder.py` Layer 4 |
| F-13 First-Turn Contract | `conversation_orchestrator.py` → `_plan_next_response` | `STAGE_GUIDANCE["DOOR_OPEN"]` |

### Priority Order

Implement in this order — each one builds on the last:

1. **F-13** — First-turn naturalness (smallest change, highest ROI)
2. **F-12** — Communication style wiring (already computed, just unused)
3. **F-04** — Interruption escalation (builds on existing streak counter)
4. **F-01** — Emotion momentum (makes everything else feel earned)
5. **F-08** — Posture/friction conflict detection (prevents contradictory outputs)
6. **F-03** — Semantic anchor validation (prevents mixed signals to LLM)
7. **F-02** — Friction memory (plateau effect)
8. **F-05** — Homeowner fatigue (turn length sensitivity)
9. **F-06** — Objection fatigue (escalate or resign)
10. **F-07** — Weighted booking gates (scoring overhaul)
11. **F-09** — Bidirectional signals (new class, most complex)
12. **F-11** — Objection carryover quality (realism eval improvement)
13. **F-10** — Testing claims enforcement (depends on F-09 signals)

### Testing Approach

After each feature, run the following manual test via `scripts/show_transcript.py`:

1. **F-13 test:** Open with "hey how's it going" → homeowner should say something natural, no objections
2. **F-04 test:** Raise price concern, ignore it twice, ignore it a third time → escalation should be visible in transcript
3. **F-01 test:** Build rapport for 3 turns, then say something pushy → should take 2+ good turns to recover
4. **F-05 test:** Talk for 16+ turns → homeowner should signal wanting to wrap up
5. **F-06 test:** Raise same objection 3+ times → either escalates to dealbreaker or de-prioritizes

### Do Not Change

- The `TurnAnalysis` → `HomeownerResponsePlan` contract shape (mobile app depends on this)
- The `canonical_transcript` artifact schema (show_transcript.py depends on this)
- The existing `STAGE_GUIDANCE` keys (changing keys would require migration)
- The `EMOTION_ORDER` list (changing order changes all relative logic)

---

## Success Metrics

A drill session passes the realism bar when:

1. Turn 1 response is socially natural — responds to what was actually said
2. Social proof claims (neighbor, nearby house) get an explicit reaction in the same turn
3. Ignored objections escalate across turns, not just within the same stage
4. Emotion transitions take 2+ turns in the positive direction, 0 turns in the negative direction
5. Long conversations (15+ turns) produce visible wrap-up signals from the homeowner
6. Transcript reads like a real door interaction, not a customer service call

The `ConversationRealismEvalService` score should target ≥ 0.75 across all four dimensions (directness, objection_carryover, emotional_consistency, closing_resistance) after these changes are implemented.

---

*Document generated from session analysis + codebase review. Implementation may require reading `micro_behavior_engine.py` and `prompt_builder.py` for Layer injection points.*
