# DoorDrill

An AI-powered voice training platform for door-to-door sales reps.

## The Problem

Door-to-door sales — pest control, solar, home security — is one of the few industries where training still relies almost entirely on repetition, ride-alongs, and trial by fire. Companies invest weeks or months ramping new reps before summer selling season, and the feedback loop during that ramp is painfully slow.

The current process looks like this: a rep records a voice memo of their pitch and texts it to their manager. The manager listens when they get a chance, types out feedback in a text thread, and the rep tries again. This cycle might happen once or twice a day if the manager is on top of it. If they're managing a team of 15-20 reps, most recordings don't get listened to at all.

The real problem isn't that managers don't care — it's that the process doesn't scale. There's no structured way to practice the hundreds of edge cases that come up at the door. A homeowner who says their spouse isn't home. Someone who already has a pest control provider. A person who's interested but wants to think about it. Each of these requires a different response, and the only way reps learn to handle them today is by failing in front of real customers.

By the time a rep gets meaningful feedback on a bad interaction, they've already repeated the same mistake a dozen more times.

## The Solution

DoorDrill replaces the voice-memo-and-text-feedback loop with a real-time AI training partner. Reps open the app, start a session, and have a live voice conversation with an AI homeowner who responds naturally, raises realistic objections, and reacts to what the rep actually says.

The AI doesn't follow a script. It plays a character — a skeptical retiree, a busy parent, someone who just signed with a competitor — and the rep has to adapt in real time, just like they would on an actual porch. Managers build the training path by assigning specific scenarios to their reps based on the skills they need to develop. A new rep might start with a friendly homeowner and a simple pitch. A more experienced rep might get thrown into a hostile interaction with multiple objections stacked on top of each other.

After each session, the conversation is graded automatically against a rubric that evaluates the things managers actually care about: did the rep open well, did they handle the objection, did they ask for the sale, were they professional throughout. The rep gets a scorecard with specific feedback. The manager gets a notification with scores and a summary, and can listen to the audio or read the transcript if they want to dig deeper. They can override the AI's grade or add their own notes.

The result is that reps can practice dozens of realistic interactions per day instead of waiting hours for feedback on one. Managers can track their entire team's progress at a glance instead of drowning in voice memos. And when summer hits, reps show up on day one having already worked through the scenarios that used to take weeks of real-world stumbling to learn.

## Why This Matters

The door-to-door sales industry is massive and largely underserved by technology. Companies spend real money on training — flights, hotels, multi-week boot camps — and still lose a significant percentage of new reps in their first summer because they weren't ready. If DoorDrill can demonstrably shorten ramp time or improve close rates, the ROI case for sales orgs is straightforward.

The platform starts with pest control because that's where the deepest domain expertise and early testing relationships are. But the underlying system — AI roleplay, structured rubrics, manager oversight — applies directly to solar, home security, roofing, and any other industry where reps are selling face-to-face at the door. The scenario library and persona system are designed to expand across verticals without rebuilding the core product.

## How It Works

1. A manager assigns a scenario to a rep (or a group of reps) through the platform.
2. The rep opens the mobile app, sees their assignment, and starts a session.
3. The rep speaks naturally into their phone. Their voice is transcribed in real time and fed to an LLM that's playing the role of a homeowner with a specific personality, set of concerns, and objections.
4. The AI homeowner responds with synthesized speech. The conversation flows back and forth like a real interaction at the door.
5. When the session ends, the full transcript is evaluated against a grading rubric by a separate AI agent. Scores are generated across categories like opening, pitch delivery, objection handling, closing technique, and professionalism.
6. The rep sees their scorecard with specific feedback and highlighted moments from the conversation.
7. The manager receives a summary with scores. They can review the transcript, listen to audio, override grades, or add notes.
8. Over time, both the rep and the manager can see progress trends — which skills are improving, which still need work.

## Technical Overview

The platform consists of three main pieces:

**Mobile app** (React Native) — where reps practice. The core screen is a real-time voice interface that streams audio to the backend over WebSockets and plays back the AI's responses.

**Backend** (Python / FastAPI) — handles the real-time voice pipeline, conversation logic, grading, and all API endpoints. The voice pipeline chains together streaming speech-to-text, an LLM for conversation, and text-to-speech for the AI homeowner's voice. Grading runs asynchronously after each session using a separate LLM call with structured rubrics.

**Manager dashboard** (web) — where managers assign scenarios, review sessions, track team progress, and provide manual feedback.

See `architecture.md` for the full system design, data model, API specification, cost analysis, and implementation roadmap.

## Status

Early stage. Currently in design and prototyping.

## Backend Progress

The initial FastAPI backend foundation has been implemented in [`backend/`](./backend):

- Assignment workflow (`manager -> rep`)
- Realtime WebSocket voice session contract
- Immutable session interaction ledger
- Post-session grading + manager override workflow
- Manager replay endpoint with transcript + artifact links

## Dashboard Progress

A manager web scaffold has been implemented in [`dashboard/`](./dashboard):

- Feed view (`/manager/feed`)
- Session replay detail (`/manager/sessions/{id}/replay`)
- Score override action (`PATCH /manager/scorecards/{id}`)
- Follow-up assignment action (`POST /manager/scorecards/{id}/followup-assignment`)
