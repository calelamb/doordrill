# PHASE 6 --- EMOTION & OBJECTION SIMULATION ENGINE

Objective: Upgrade the simulation system to model realistic homeowner
behavior using an emotional state machine and objection escalation
logic.

Background: Real door-to-door interactions involve emotional responses
and escalating objections. The simulation must model these dynamics.

Codex Instructions:

Design and implement an emotional state system for AI homeowners.

Core emotional states:

neutral skeptical annoyed interested hostile curious

State transitions should depend on rep behavior.

Examples:

rep ignores objection → increase annoyance rep acknowledges concern →
decrease resistance rep builds rapport → increase openness

Add an emotional state variable to the conversation engine.

Evaluate how persona and scenario inputs influence starting state.

Create:

EMOTION_SIMULATION_ENGINE.md

Include:

-   emotional state diagram
-   transition rules
-   integration points with the conversation engine
-   example behavioral responses for each state
