# PHASE 10 --- NOVEL HOMEOWNER AI SIMULATOR

Objective: start implementation planning for a differentiated homeowner
simulation system that feels less like generic roleplay and more like a
real, stateful door interaction.

Why this phase exists:

- The current repo already has a usable conversation orchestrator,
  scenario model, objection tagging, interruption tracing, and replay
  evidence.
- The next step is not "add more prompts." The next step is to turn the
  homeowner into a simulation engine with memory, state, behavioral
  variability, and measurable realism.
- This phase should work with the existing workflow docs, especially
  Phases 3, 4, 6, 7, and 8.

This phase builds on:

- `for codex 3:6/PHASE_3_SIMULATION_REALISM_AUDIT.md`
- `for codex 3:6/PHASE_4_PROMPT_ENGINEERING_REVIEW.md`
- `for codex 3:6/PHASE_6_EMOTION_OBJECTION_ENGINE.md`
- `for codex 3:6/PHASE_7_ADAPTIVE_DIFFICULTY_SKILL_GRAPH.md`
- `for codex 3:6/PHASE_8_CONVERSATIONAL_MICRO_BEHAVIORS.md`
- `architecture.md`
- `PHASE_GAP_ANALYSIS_20260306.md`

Product standard:

The homeowner should behave like a believable human with goals,
constraints, preferences, emotional reactions, and conversational
imperfections. The simulation must remain fast enough for live voice and
deterministic enough for repeatable training outcomes.

Core simulator principles:

- stateful, not stateless
- behavior-driven, not only prompt-driven
- scenario-aware, not generic-chat-aware
- fast enough for real-time voice use
- replayable and explainable for managers
- measurable with explicit realism and training metrics

Implementation thesis:

The novel simulator should be a layered system:

1. persona foundation
2. world-state and household context
3. emotion and resistance state machine
4. objection policy and escalation planner
5. conversational micro-behavior renderer
6. adaptive difficulty controls
7. analytics and evaluation hooks

Codex Instructions:

Produce a concrete execution plan and begin with the smallest set of
backend-first changes that unlock the simulator architecture without
breaking the current live loop.

Create:

`NOVEL_HOMEOWNER_SIMULATOR_EXECUTION_PLAN.md`

The plan must include the following tracks.

Track A --- Simulation Kernel

Goal:

Create a dedicated simulator domain model instead of continuing to pack
new behavior into loose prompt fields.

Required design outputs:

- homeowner state object
- turn context object
- scenario policy object
- response plan object
- transition function boundaries

Likely code touchpoints:

- `backend/app/services/conversation_orchestrator.py`
- `backend/app/models/scenario.py`
- `backend/app/schemas/scenario.py`
- `scenarios/`

Track B --- Persona and Household Memory

Goal:

Model the homeowner as a person in a real environment, not just a list
of objections.

Required concepts:

- household composition
- prior service history
- current emotional baseline
- time pressure
- risk tolerance
- purchasing authority
- neighborhood context
- memory of what the rep has already said

Output expectations:

- richer persona schema
- defaults and validation rules
- migration strategy for existing scenarios

Track C --- Emotion and Resistance Engine

Goal:

Convert "skeptical" and "annoyed" from prompt adjectives into explicit
state with transitions.

Required mechanics:

- emotional state enum
- resistance/openness score
- transition rules driven by rep behavior
- decay / recovery rules
- hard-stop conditions for hostile or disengaged homeowners

This track should extend Phase 6 rather than replacing it.

Track D --- Objection Choreography

Goal:

Make objections feel sequenced, conditional, and cumulative.

Required mechanics:

- objection queue + branching rules
- trigger conditions
- resolved vs unresolved objection tracking
- escalation when concerns are ignored
- softening when concerns are acknowledged well

The homeowner should not repeat the same objection pattern every time.

Track E --- Conversational Micro-Behaviors

Goal:

Introduce human messiness after response planning and before TTS.

Required mechanics:

- hesitation injection
- filler-word policy
- sentence-length variance
- pause timing model
- interruption behavior tied to emotional state
- tone-style modifiers that do not destroy clarity

This track should align with Phase 8 and integrate with
`backend/app/voice/ws.py`.

Track F --- Adaptive Difficulty and Skill Coupling

Goal:

Use rep skill history to choose how hard the homeowner should be.

Required mechanics:

- rep skill profile inputs
- scenario difficulty controls
- patience window
- objection density
- conversational resistance tuning
- recommended next scenario logic

This track should align with Phase 7 and reuse analytics when possible
instead of inventing a second scoring system.

Track G --- Replay, Analytics, and Explainability

Goal:

Ensure the simulator is inspectable after the fact.

Required telemetry:

- emotional state timeline
- objection state timeline
- response-plan annotations
- interruption cause markers
- realism markers for manager replay

Manager-facing outcome:

Managers should be able to see not only what happened, but why the
simulator behaved that way.

Track H --- Evaluation Harness

Goal:

Measure realism and training usefulness before broad rollout.

Required validation artifacts:

- seeded transcript replay tests
- deterministic simulator-state tests
- prompt regression tests
- latency impact checks
- realism score rubric
- failure catalog of unrealistic behaviors

Track I --- Rollout Plan

Goal:

Ship incrementally without destabilizing current training.

Recommended rollout order:

1. simulator data model
2. internal response-planning layer
3. emotion/resistance engine
4. objection choreography
5. micro-behavior renderer
6. replay instrumentation
7. adaptive difficulty hooks
8. manager-visible simulator analytics

Implementation constraints:

- live voice latency remains a hard constraint
- simulator logic must be testable outside the WebSocket loop
- prompt templates should become thinner as behavior logic becomes more
  explicit
- manager analytics must consume derived simulator telemetry, not raw
  ad hoc transcript parsing
- existing scenarios must continue to run during migration

Specific questions Codex must answer in the execution plan:

- Which simulator state should be persisted per turn vs derived on
  replay?
- What belongs in code vs in scenario YAML?
- Which parts of homeowner behavior should be deterministic vs
  stochastic?
- How will we keep repeated drills varied without making evaluation
  inconsistent?
- What is the minimum viable simulator that feels novel to reps?
- Which existing backend components can be extended safely, and which
  should be split before adding more logic?

Deliverables for this phase:

- a detailed execution plan with dependency order
- a proposed data contract for simulator state
- a migration approach for existing scenarios
- a testing strategy for realism and latency
- a recommendation for the first implementation slice

Recommended first implementation slice:

Build a small simulator kernel that adds:

- explicit emotional state
- objection progression state
- response planning metadata
- replay-visible simulator telemetry

That slice is large enough to change realism materially and small enough
to validate before adding skill adaptation and richer household memory.

Success condition:

At the end of this phase, DoorDrill should have a concrete engineering
plan to turn the homeowner from a prompt persona into a novel simulator
system that can support realism, adaptive difficulty, replay
explainability, and manager trust.
