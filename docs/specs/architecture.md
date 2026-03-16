# DoorDrill — AI Sales Training Platform

## Architecture Overview

**An AI-powered real-time voice training app for door-to-door sales reps, starting with pest control.**

Reps practice live voice conversations with AI homeowner personas. Sessions are graded automatically and surfaced to managers for review.

---

## System Architecture (High-Level)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MOBILE APP (React Native)                    │ 
│                                                                     │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────────┐ │
│  │  Auth /   │  │  Scenario    │  │  Live Voice │  │  Session     │ │
│  │  Onboard  │  │  Launcher    │  │  Interface  │  │  History     │ │
│  └──────────┘  └──────────────┘  └─────┬──────┘  └──────────────┘ │
│                                        │ WebSocket                  │
└────────────────────────────────────────┼────────────────────────────┘
                                         │
                          ┌──────────────┼──────────────┐
                          │    REAL-TIME VOICE GATEWAY   │
                          │    (FastAPI + WebSockets)    │
                          │                              │
                          │  ┌────────┐  ┌───────────┐  │
                          │  │ STT    │  │ TTS       │  │
                          │  │ Stream │  │ Stream    │  │
                          │  └───┬────┘  └─────┬─────┘  │
                          │      │             │         │
                          └──────┼─────────────┼─────────┘
                                 │             │
                          ┌──────▼─────────────▼─────────┐
                          │      CONVERSATION ENGINE      │
                          │      (LLM Orchestrator)       │
                          │                               │
                          │  ┌─────────────────────────┐  │
                          │  │  Persona + Scenario      │  │
                          │  │  System Prompt Builder    │  │
                          │  └─────────────────────────┘  │
                          │  ┌─────────────────────────┐  │
                          │  │  Conversation State      │  │
                          │  │  Manager                 │  │
                          │  └─────────────────────────┘  │
                          │  ┌─────────────────────────┐  │
                          │  │  LLM API Client          │  │
                          │  │  (Claude / GPT-5.2)       │  │
                          │  └─────────────────────────┘  │
                          └──────────────┬────────────────┘
                                         │
                          ┌──────────────▼────────────────┐
                          │        GRADING ENGINE          │
                          │   (Async Post-Session Agent)   │
                          │                                │
                          │  ┌──────────────────────────┐  │
                          │  │  Rubric Evaluator (LLM)  │  │
                          │  └──────────────────────────┘  │
                          │  ┌──────────────────────────┐  │
                          │  │  Score Calculator         │  │
                          │  └──────────────────────────┘  │
                          │  ┌──────────────────────────┐  │
                          │  │  Notification Dispatcher  │  │
                          │  └──────────────────────────┘  │
                          └──────────────┬────────────────┘
                                         │
                          ┌──────────────▼────────────────┐
                          │          DATA LAYER            │
                          │                                │
                          │  ┌────────────┐ ┌───────────┐ │
                          │  │ PostgreSQL │ │  S3 /     │ │
                          │  │ (Core DB)  │ │  Audio    │ │
                          │  └────────────┘ └───────────┘ │
                          │  ┌────────────┐ ┌───────────┐ │
                          │  │ Redis      │ │  Celery   │ │
                          │  │ (Sessions) │ │  (Tasks)  │ │
                          │  └────────────┘ └───────────┘ │
                          └───────────────────────────────┘
                                         │
                          ┌──────────────▼────────────────┐
                          │     REST API (FastAPI)         │
                          │                                │
                          │  Manager Endpoints:            │
                          │  - Assign scenarios to reps    │
                          │  - View scores & transcripts   │
                          │  - Manual override grades      │
                          │  - Rep progress dashboard      │
                          │                                │
                          │  Rep Endpoints:                 │
                          │  - View assigned scenarios      │
                          │  - Session history & scores     │
                          │  - Replay past sessions         │
                          └───────────────────────────────┘
```

---

## Component Deep Dives

### 1. Real-Time Voice Pipeline

This is the most latency-sensitive piece. The goal is < 1 second end-to-end (rep stops talking → AI homeowner starts responding).

```
REP SPEAKS
    │
    ▼
┌─────────────────────────────────┐
│  Audio Capture (React Native)   │
│  - 16kHz PCM or Opus codec      │
│  - Voice Activity Detection      │
│    (VAD) on-device               │
│  - Stream chunks via WebSocket   │
└───────────────┬─────────────────┘
                │ audio chunks
                ▼
┌─────────────────────────────────┐
│  Speech-to-Text (Streaming)     │
│                                 │
│  Option A: Deepgram Nova-2      │
│  - Best streaming latency       │
│  - ~300ms to first token        │
│  - WebSocket native             │
│                                 │
│  Option B: OpenAI Whisper API   │
│  - Better accuracy              │
│  - Higher latency (~1-2s)       │
│  - Batch, not streaming         │
│                                 │
│  Recommendation: Deepgram for   │
│  real-time, Whisper for post-   │
│  session transcript cleanup     │
└───────────────┬─────────────────┘
                │ text transcript
                ▼
┌─────────────────────────────────┐
│  LLM Conversation Engine        │
│                                 │
│  - Receives transcribed text    │
│  - Maintains conversation       │
│    history in memory             │
│  - Streams response tokens      │
│  - ~500ms to first token        │
│    (Claude Sonnet / GPT-4o)     │
└───────────────┬─────────────────┘
                │ text response (streamed)
                ▼
┌─────────────────────────────────┐
│  Text-to-Speech (Streaming)     │
│                                 │
│  Option A: ElevenLabs           │
│  - Most natural voices          │
│  - Streaming support            │
│  - ~400ms to first audio        │
│  - $$$ at scale                 │
│                                 │
│  Option B: OpenAI TTS           │
│  - Good quality, cheaper        │
│  - Less voice variety           │
│                                 │
│  Option C: Deepgram Aura        │
│  - Fastest latency              │
│  - Lower quality                │
│                                 │
│  Recommendation: Start with     │
│  ElevenLabs for quality, have   │
│  an abstraction layer to swap   │
└───────────────┬─────────────────┘
                │ audio stream
                ▼
         REP HEARS RESPONSE
```

**Latency Budget:**

| Stage | Target | Notes |
|-------|--------|-------|
| VAD + audio send | ~100ms | On-device, minimal |
| STT (Deepgram streaming) | ~300ms | First partial transcript |
| LLM first token | ~500ms | Claude Sonnet or GPT-4o |
| TTS first audio | ~400ms | ElevenLabs streaming |
| **Total** | **~1.3s** | **Acceptable for conversation** |

**Key design decision:** Start sending text to TTS as the LLM streams tokens. Don't wait for the full LLM response. This shaves 500ms+ off perceived latency.

---

### 2. Conversation Engine

The brain of the system. This is where your domain expertise becomes the product.

```python
# Simplified architecture of the conversation engine

class ConversationEngine:
    """
    Orchestrates a single training session between a rep and AI homeowner.
    One instance per active session.
    """

    def __init__(self, scenario: Scenario, persona: HomeownerPersona):
        self.scenario = scenario
        self.persona = persona
        self.transcript = []
        self.state = ConversationState.DOOR_KNOCK

    def build_system_prompt(self) -> str:
        """
        Constructs the LLM system prompt from scenario + persona.
        THIS IS YOUR SECRET SAUCE.
        """
        return f"""
        You are roleplaying as a homeowner answering their front door.

        YOUR PERSONA:
        - Name: {self.persona.name}
        - Attitude: {self.persona.attitude}
        - Key concerns: {', '.join(self.persona.concerns)}
        - Likelihood to buy: {self.persona.buy_likelihood}
        - Objections you will raise: {', '.join(self.persona.objections)}

        SCENARIO: {self.scenario.description}
        CURRENT STAGE: {self.state.value}

        RULES:
        - Stay in character at all times
        - React naturally to what the rep says
        - If the rep handles your objection well, soften slightly
        - If the rep is pushy or ignores your concern, get annoyed
        - Never break character or acknowledge this is a simulation
        - Keep responses to 1-3 sentences (natural speech length)
        """

    async def process_rep_input(self, text: str) -> AsyncGenerator[str, None]:
        """Process rep's speech and stream AI homeowner response."""
        self.transcript.append({"role": "rep", "text": text})

        async for token in self.llm.stream(
            system=self.build_system_prompt(),
            messages=self.transcript,
        ):
            yield token

        # Update conversation state based on what happened
        self.state = self._detect_stage_transition(text)
```

**Scenario & Persona Data Model:**

```
SCENARIO
├── id
├── name (e.g., "First Door Knock - Skeptical Homeowner")
├── description
├── industry (pest_control | solar | security | ...)
├── difficulty (1-5)
├── target_skills (list of skills being tested)
├── stages (ordered list)
│   ├── DOOR_KNOCK
│   ├── INITIAL_PITCH
│   ├── OBJECTION_HANDLING
│   ├── CLOSE_ATTEMPT
│   └── WRAP_UP
└── success_criteria

HOMEOWNER PERSONA
├── id
├── name
├── attitude (friendly | skeptical | hostile | busy | ...)
├── concerns (list: price, trust, timing, spouse, ...)
├── objections (list of specific objections to raise)
├── buy_likelihood (0.0 - 1.0)
├── personality_notes (free text for LLM)
└── voice_id (ElevenLabs voice to use)
```

---

### 3. Grading Engine

Runs asynchronously after each session completes. This is the part managers care about most.

```
SESSION ENDS
    │
    ▼
┌─────────────────────────────────────────┐
│  Transcript Cleanup                      │
│  - Re-transcribe full audio w/ Whisper   │
│  - Align timestamps                      │
│  - Clean up STT artifacts                │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Rubric Evaluator (LLM-as-Judge)        │
│                                          │
│  Input: Full transcript + rubric         │
│                                          │
│  RUBRIC CATEGORIES:                      │
│  ┌─────────────────────────────────────┐ │
│  │ 1. Opening (0-10)                   │ │
│  │    - Did they introduce themselves? │ │
│  │    - Was the opener natural?        │ │
│  │    - Did they build rapport?        │ │
│  ├─────────────────────────────────────┤ │
│  │ 2. Pitch Delivery (0-10)           │ │
│  │    - Clear value proposition?       │ │
│  │    - Tailored to homeowner?         │ │
│  │    - Confident but not pushy?       │ │
│  ├─────────────────────────────────────┤ │
│  │ 3. Objection Handling (0-10)        │ │
│  │    - Acknowledged the concern?      │ │
│  │    - Provided relevant counter?     │ │
│  │    - Maintained composure?          │ │
│  ├─────────────────────────────────────┤ │
│  │ 4. Closing Technique (0-10)         │ │
│  │    - Asked for the sale?            │ │
│  │    - Used urgency appropriately?    │ │
│  │    - Handled final objections?      │ │
│  ├─────────────────────────────────────┤ │
│  │ 5. Overall Professionalism (0-10)   │ │
│  │    - Tone and pacing?               │ │
│  │    - Active listening signals?      │ │
│  │    - Respectful of boundaries?      │ │
│  └─────────────────────────────────────┘ │
│                                          │
│  Output: Scores + per-category feedback  │
│  + highlight moments (timestamps)        │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Score Card Generation                   │
│                                          │
│  {                                       │
│    "session_id": "...",                  │
│    "rep_id": "...",                      │
│    "scenario": "Skeptical Homeowner",    │
│    "overall_score": 7.2,                 │
│    "categories": {                       │
│      "opening": 8,                       │
│      "pitch": 7,                         │
│      "objections": 6,                    │
│      "closing": 7,                       │
│      "professionalism": 8               │
│    },                                    │
│    "highlights": [                       │
│      {"timestamp": "0:42", "type":       │
│       "strong", "note": "Great reframe   │
│       on price objection"},              │
│      {"timestamp": "1:15", "type":       │
│       "improve", "note": "Talked over    │
│       the homeowner here"}               │
│    ],                                    │
│    "summary": "Solid opener and good     │
│     rapport. Objection handling needs    │
│     work — missed the spouse concern.",  │
│    "manager_review_needed": false        │
│  }                                       │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Notification Dispatcher                 │
│                                          │
│  IF score < threshold OR flagged:        │
│    → Email manager with summary          │
│    → Push notification to manager app    │
│                                          │
│  ALWAYS:                                 │
│    → Push notification to rep            │
│    → Update rep's progress dashboard     │
│    → Store in session history             │
└─────────────────────────────────────────┘
```

---

### 4. Data Model

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│  ORGANIZATION │     │  USER             │     │  TEAM           │
│               │────<│                   │────<│                 │
│  id           │     │  id               │     │  id             │
│  name         │     │  org_id (FK)      │     │  org_id (FK)    │
│  industry     │     │  team_id (FK)     │     │  manager_id(FK) │
│  plan_tier    │     │  role (rep|mgr)   │     │  name           │
└──────────────┘     │  name             │     └────────────────┘
                      │  email            │
                      │  phone            │
                      └──────────────────┘
                               │
                               │ assigned_to
                               ▼
┌──────────────────┐     ┌──────────────────┐
│  SCENARIO         │     │  ASSIGNMENT       │
│                   │────<│                   │
│  id               │     │  id               │
│  name             │     │  scenario_id (FK) │
│  industry         │     │  rep_id (FK)      │
│  difficulty       │     │  assigned_by (FK) │
│  persona (JSON)   │     │  due_date         │
│  rubric (JSON)    │     │  status           │
│  stages (JSON)    │     │  min_score        │
│  created_by (FK)  │     └──────────────────┘
└──────────────────┘              │
                                  │ generates
                                  ▼
                      ┌──────────────────────┐
                      │  SESSION              │
                      │                       │
                      │  id                   │
                      │  assignment_id (FK)   │
                      │  rep_id (FK)          │
                      │  scenario_id (FK)     │
                      │  started_at           │
                      │  ended_at             │
                      │  duration_seconds     │
                      │  audio_url (S3)       │
                      │  transcript (JSON)    │
                      │  status               │
                      └───────────┬───────────┘
                                  │
                                  ▼
                      ┌──────────────────────┐
                      │  SCORE_CARD           │
                      │                       │
                      │  id                   │
                      │  session_id (FK)      │
                      │  overall_score        │
                      │  category_scores(JSON)│
                      │  highlights (JSON)    │
                      │  ai_summary           │
                      │  manager_reviewed     │
                      │  manager_notes        │
                      │  manager_override_    │
                      │    score              │
                      └───────────────────────┘
```

---

### 5. Tech Stack (Recommended)

| Layer | Technology | Why |
|-------|-----------|-----|
| **Mobile App** | React Native (Expo) | Cross-platform from day one. Expo simplifies builds. You know Python, RN is learnable fast. |
| **API Server** | FastAPI (Python) | Async-native, great for WebSockets, you already know Python. |
| **Real-time Voice** | FastAPI WebSockets | Same server, separate WS endpoint for voice streaming. |
| **STT (real-time)** | Deepgram Nova-2 | Best streaming latency, WebSocket API, good accuracy. |
| **STT (post-session)** | OpenAI Whisper API | Higher accuracy for final transcript used in grading. |
| **LLM (conversation)** | Claude Sonnet / GPT-4o | Fast, smart enough for roleplay. Swap easily via abstraction. |
| **LLM (grading)** | Claude Opus / GPT-4o | Use a stronger model for evaluation — accuracy matters more here. |
| **TTS** | ElevenLabs | Most natural voices, streaming support, good API. |
| **Database** | PostgreSQL | Rock solid, JSON support for flexible schema fields. |
| **Cache / Sessions** | Redis | In-memory session state during live conversations. |
| **Task Queue** | Celery + Redis | Async grading, notifications, transcript cleanup. |
| **Audio Storage** | AWS S3 / Cloudflare R2 | Cheap, scalable, presigned URLs for playback. |
| **Auth** | Firebase Auth or Supabase Auth | Don't build auth yourself. Social + email out of the box. |
| **Hosting** | Railway or Fly.io | Simple deployment, WebSocket support, scales easily. Solo-dev friendly. |
| **Push Notifications** | Firebase Cloud Messaging | Free, works with React Native, cross-platform. |

---

### 6. Voice Pipeline Detail — Handling Interruptions & Turn-Taking

Door-to-door conversations are messy. People talk over each other. Your voice pipeline needs to handle this.

```
INTERRUPTION HANDLING:

1. Rep is talking, AI is silent
   → Normal flow: STT → LLM → TTS

2. AI is responding, rep starts talking (interruption)
   → Immediately stop TTS playback
   → Buffer rep's audio
   → When rep stops (VAD), process their input
   → AI responds to the interruption naturally

3. Awkward silence (>3 seconds, no one talking)
   → AI homeowner fills the gap naturally
     ("So... is there something else?" or
      "Look, I really need to get back inside")

4. Both talking simultaneously
   → Rep audio takes priority
   → Stop AI TTS
   → Process rep's speech
```

**Implementation approach:**

```python
class VoiceSession:
    """Manages real-time voice state for one session."""

    def __init__(self):
        self.ai_speaking = False
        self.rep_speaking = False
        self.silence_timer = None
        self.tts_cancel_event = asyncio.Event()

    async def on_rep_voice_activity(self, is_speaking: bool):
        if is_speaking and self.ai_speaking:
            # Rep interrupted — cancel TTS immediately
            self.tts_cancel_event.set()
            self.ai_speaking = False

        if not is_speaking:
            # Rep stopped — reset silence timer
            self.reset_silence_timer()

    async def silence_timeout(self):
        """Trigger AI to fill awkward silence."""
        await asyncio.sleep(3.0)
        if not self.rep_speaking and not self.ai_speaking:
            await self.engine.generate_filler_response()
```

---

### 7. API Endpoints

```
AUTH
  POST   /auth/register          # Create account (rep or manager)
  POST   /auth/login              # Get JWT token
  POST   /auth/refresh            # Refresh token

MANAGER ENDPOINTS
  GET    /manager/team                    # List reps on team
  POST   /manager/assignments             # Assign scenario to rep(s)
  GET    /manager/assignments             # List all assignments
  GET    /manager/sessions                # List all sessions (filterable)
  GET    /manager/sessions/:id            # Session detail + scorecard
  GET    /manager/sessions/:id/audio      # Presigned audio URL
  PATCH  /manager/scorecards/:id          # Override score, add notes
  GET    /manager/reps/:id/progress       # Rep progress over time
  GET    /manager/analytics               # Team-wide stats

REP ENDPOINTS
  GET    /rep/assignments                 # My assigned scenarios
  POST   /rep/sessions                    # Start a new session
  GET    /rep/sessions                    # My session history
  GET    /rep/sessions/:id                # Session detail + score
  GET    /rep/progress                    # My progress over time

SCENARIOS (manager-only create/edit)
  GET    /scenarios                        # List available scenarios
  POST   /scenarios                        # Create custom scenario
  GET    /scenarios/:id                    # Scenario detail
  PUT    /scenarios/:id                    # Edit scenario

VOICE (WebSocket)
  WS     /ws/session/:session_id          # Real-time voice channel
```

---

### 8. MVP Scope (What to Build First)

Given that you're a solo developer, here's the phased approach:

```
PHASE 1 — PROOF OF CONCEPT (2-4 weeks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Goal: Prove the voice loop works and feels real.

Build:
  ✓ FastAPI server with one WebSocket endpoint
  ✓ Deepgram STT streaming integration
  ✓ LLM conversation with ONE hardcoded persona
  ✓ ElevenLabs TTS streaming back to client
  ✓ Simple React Native screen: tap to talk, hear response
  ✓ Basic turn-taking (no interruption handling yet)

Skip for now:
  ✗ Auth, database, grading, manager features
  ✗ Multiple scenarios or personas
  ✗ Session recording or playback

Validation: Have 3-5 reps try it. Do they come back?


PHASE 2 — CORE PRODUCT (4-6 weeks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Goal: Usable training tool with grading.

Build:
  ✓ Auth (Firebase/Supabase)
  ✓ PostgreSQL data model
  ✓ 5-8 scenarios with different personas
  ✓ Post-session grading engine
  ✓ Rep session history + score cards
  ✓ Audio recording + S3 storage
  ✓ Manager: assign scenarios via API/simple web UI
  ✓ Email notifications to managers on session completion

Skip for now:
  ✗ Full manager dashboard
  ✗ Analytics / progress tracking
  ✗ Interruption handling
  ✗ Multiple industries


PHASE 3 — MANAGER EXPERIENCE (3-4 weeks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Goal: Managers can run their team through the app.

Build:
  ✓ Web dashboard for managers
  ✓ Rep progress charts over time
  ✓ Audio playback with transcript + highlights
  ✓ Manager score override and notes
  ✓ Team analytics (avg scores, completion rates)
  ✓ Push notifications

Skip for now:
  ✗ Custom scenario builder UI
  ✗ Multi-industry support


PHASE 4 — SCALE & EXPAND (ongoing)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Custom scenario builder for managers
  ✓ Solar, security, and other industries
  ✓ Advanced interruption handling
  ✓ Rep-vs-rep leaderboards
  ✓ Spaced repetition (weak areas resurface)
  ✓ Onboarding flow for new organizations
```

---

### 9. Cost Estimates (Per Training Session)

Assuming a 5-minute session (~2.5 min rep talking, ~2.5 min AI talking):

| Service | Usage | Est. Cost |
|---------|-------|-----------|
| Deepgram STT | ~2.5 min audio | ~$0.006 |
| LLM (Claude Sonnet) | ~4K tokens in, ~2K out | ~$0.02 |
| LLM (Grading - Opus) | ~6K tokens in, ~1K out | ~$0.10 |
| ElevenLabs TTS | ~500 chars streamed | ~$0.02 |
| Whisper (post-session) | ~5 min audio | ~$0.03 |
| S3 Storage | ~5MB audio | ~$0.0001 |
| **Total per session** | | **~$0.18** |

At $0.18/session, if you charge $50/rep/month and each rep does 30 sessions, your cost is ~$5.40/rep/month. That's solid unit economics.

---

### 10. Key Technical Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Voice latency too high | Feels unnatural, reps won't use it | Start TTS as LLM streams. Use Deepgram for STT. Benchmark early. |
| LLM breaks character | Ruins immersion | Strong system prompts. Test extensively. Add guardrails for off-topic detection. |
| Grading inconsistency | Managers don't trust scores | Use structured rubrics. Let managers override. Calibrate with real manager feedback. |
| React Native audio issues | WebSocket + mic on mobile is tricky | Use expo-av or react-native-audio-api. Test on real devices early. |
| Solo dev burnout | Scope creep kills the project | Ruthless Phase 1 scoping. Ship the voice loop first. Everything else is iteration. |

---

### 11. Folder Structure (Suggested)

```
doordrill/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app entry
│   │   ├── config.py               # Environment config
│   │   ├── models/                 # SQLAlchemy models
│   │   │   ├── user.py
│   │   │   ├── scenario.py
│   │   │   ├── session.py
│   │   │   └── scorecard.py
│   │   ├── api/                    # REST endpoints
│   │   │   ├── auth.py
│   │   │   ├── manager.py
│   │   │   ├── rep.py
│   │   │   └── scenarios.py
│   │   ├── voice/                  # Real-time voice pipeline
│   │   │   ├── gateway.py          # WebSocket handler
│   │   │   ├── stt.py              # Deepgram integration
│   │   │   ├── tts.py              # ElevenLabs integration
│   │   │   └── session.py          # Voice session state
│   │   ├── engine/                 # Conversation + grading
│   │   │   ├── conversation.py     # LLM orchestration
│   │   │   ├── personas.py         # Persona/scenario builder
│   │   │   └── grading.py          # Post-session evaluation
│   │   ├── tasks/                  # Celery async tasks
│   │   │   ├── grade_session.py
│   │   │   └── notifications.py
│   │   └── services/               # External service clients
│   │       ├── llm.py              # LLM abstraction layer
│   │       ├── storage.py          # S3 client
│   │       └── email.py            # Notification sender
│   ├── tests/
│   ├── alembic/                    # DB migrations
│   ├── requirements.txt
│   └── Dockerfile
├── mobile/
│   ├── src/
│   │   ├── screens/
│   │   │   ├── LoginScreen.tsx
│   │   │   ├── AssignmentsScreen.tsx
│   │   │   ├── SessionScreen.tsx    # THE voice training screen
│   │   │   ├── HistoryScreen.tsx
│   │   │   └── ScoreScreen.tsx
│   │   ├── components/
│   │   ├── services/
│   │   │   ├── api.ts              # REST client
│   │   │   ├── websocket.ts        # Voice WebSocket
│   │   │   └── audio.ts            # Mic + speaker management
│   │   └── navigation/
│   ├── app.json                    # Expo config
│   └── package.json
├── dashboard/                      # Manager web dashboard (Phase 3)
│   └── (Next.js or similar)
└── scenarios/                      # Scenario definition files
    ├── pest_control/
    │   ├── skeptical_homeowner.yaml
    │   ├── price_objection.yaml
    │   ├── spouse_not_home.yaml
    │   └── already_has_service.yaml
    └── rubrics/
        └── pest_control_v1.yaml
```

---

### 12. Alternative: OpenAI Realtime API

Worth noting — OpenAI's Realtime API handles the entire voice pipeline (STT → LLM → TTS) in one WebSocket connection with ~500ms latency. This would massively simplify your Phase 1:

**Pros:** One integration instead of three. Lower latency. Simpler architecture.
**Cons:** Vendor lock-in to OpenAI. Less control over individual components. Can't swap STT/TTS independently. Pricing may be higher.

If your goal is fastest path to a working prototype, the Realtime API is worth considering for Phase 1, then decomposing into separate services later if you need more control.

---

*This architecture is designed for a solo developer building iteratively. Phase 1 is intentionally minimal — prove the voice loop works, then layer on everything else.*
