# PHASE M4 — Real-Time Session Monitor
# Goal: Managers can see which reps are drilling RIGHT NOW, watch a live session
# unfold, and get notified the moment a session finishes or flags a red flag.
# No other D2D training tool has this. This is the differentiator.

---

## Files to read first (required before touching anything)

- `backend/app/routers/sessions.py` — the existing WebSocket gateway for rep sessions
- `backend/app/models/` — Session model, understand session status lifecycle
- `dashboard/src/lib/types.ts` — `FeedItem`, `TranscriptTurn`, `ReplayResponse`
- `dashboard/src/lib/api.ts` — `fetchManagerFeed`, `getRepSessionWsUrl`
- `dashboard/src/pages/ManagerFeedPage.tsx` — the feed that will show live sessions
- `dashboard/src/pages/ManagerReplayPage.tsx` — the replay view (we'll adapt this for live)

---

## Part 1: Backend — Live Session State API

### New endpoint: GET /manager/sessions/live

Add to `backend/app/routers/manager.py`.

**Query params:** `manager_id`

**Logic:**
- Query sessions table for sessions with `status = 'active'` where `rep_id` belongs to this manager's team
- Join with reps, scenarios tables
- Return lightweight session cards

**Response schema:**
```python
class LiveSessionCard(BaseModel):
    session_id: str
    rep_id: str
    rep_name: str
    scenario_id: str
    scenario_name: str
    scenario_difficulty: int
    started_at: str  # ISO
    elapsed_seconds: int  # computed: now - started_at
    stage: str | None  # current conversation stage if available
    turn_count: int  # how many turns have happened

class LiveSessionsResponse(BaseModel):
    manager_id: str
    live_sessions: List[LiveSessionCard]
    checked_at: str  # ISO timestamp
```

**Note:** `stage` and `turn_count` can be derived from the `transcript_turns` table — count rows for this session_id.

---

### New endpoint: GET /manager/sessions/live/stream (Server-Sent Events)

This is an SSE endpoint, not WebSocket. SSE is appropriate here because:
- Manager is a passive observer (read-only, no need for bidirectional comms)
- SSE reconnects automatically
- Works through standard HTTP/2 proxies without WS upgrade complexity

**Implementation:**
```python
from fastapi.responses import StreamingResponse
import asyncio

@router.get("/manager/sessions/live/stream")
async def live_sessions_stream(manager_id: str, ...):
    async def event_generator():
        while True:
            live = await get_live_sessions_for_manager(manager_id)
            data = json.dumps(live.dict())
            yield f"data: {data}\n\n"
            await asyncio.sleep(5)  # poll every 5 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        }
    )
```

---

### New endpoint: GET /manager/sessions/:sessionId/live-transcript

Returns the current partial transcript for a live session (for the observer view).

**Logic:**
- Query `transcript_turns` for `session_id`, ordered by `turn_index`
- Also return current stage from the last turn
- This is a regular HTTP poll endpoint (not streaming), called every 3 seconds by the observer view

**Response:** Same shape as `ReplayResponse.transcript_turns` + `stage_timeline`

---

## Part 2: Frontend — Types

Add to `dashboard/src/lib/types.ts`:

```typescript
export type LiveSessionCard = {
  session_id: string;
  rep_id: string;
  rep_name: string;
  scenario_id: string;
  scenario_name: string;
  scenario_difficulty: number;
  started_at: string;
  elapsed_seconds: number;
  stage: string | null;
  turn_count: number;
};

export type LiveSessionsResponse = {
  manager_id: string;
  live_sessions: LiveSessionCard[];
  checked_at: string;
};
```

Add to `dashboard/src/lib/api.ts`:

```typescript
export async function fetchLiveSessions(managerId: string): Promise<LiveSessionsResponse> {
  return requestJson<LiveSessionsResponse>(
    `/manager/sessions/live?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchLiveTranscript(
  managerId: string,
  sessionId: string
): Promise<{ turns: TranscriptTurn[]; stage_timeline: ReplayResponse["stage_timeline"] }> {
  return requestJson(
    `/manager/sessions/${encodeURIComponent(sessionId)}/live-transcript?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
}
```

---

## Part 3: Frontend — Live Session Banner (ManagerFeedPage.tsx)

Add a "LIVE NOW" section at the top of `ManagerFeedPage.tsx`, above the filters.

**Design:**

When no live sessions:
- Section is hidden (renders nothing)

When 1+ live sessions:
```
┌──── LIVE NOW ────────────────────────────────────────┐
│ 🔴 2 reps are drilling right now                     │
│                                                       │
│  [Jordan M. — Skeptical Homeowner — 4:32 elapsed]    │
│   Stage: Objection Handling          [Watch Live →]  │
│                                                       │
│  [Sarah K. — Aggressive Skeptic — 1:12 elapsed]      │
│   Stage: Opening                     [Watch Live →]  │
└──────────────────────────────────────────────────────┘
```

- Pulsing red dot next to "LIVE NOW" using CSS animation: `animate-pulse`
- Elapsed time ticks up every second using `setInterval` in React state
- Stage label updates every 5 seconds via SSE stream
- "Watch Live →" button navigates to the live observer view

**Implementation:**
- On mount: call `fetchLiveSessions`, set results in state
- Subscribe to SSE stream at `/manager/sessions/live/stream` using native `EventSource` API
- On each SSE event: parse JSON, update live sessions state
- Cleanup `EventSource` on unmount

---

## Part 4: Frontend — Live Observer View

Create `dashboard/src/pages/LiveSessionPage.tsx`.

Add route to `App.tsx`:
```tsx
<Route path="/manager/sessions/:id/live" element={<LiveSessionPage />} />
```

**Design:**
```
┌─────────────────────────────────────────────────────┐
│ 🔴 LIVE  Jordan M. — Skeptical Homeowner            │
│ Elapsed: 4:47  Stage: Objection Handling  Diff: ●●●│
│                                                     │
│ LIVE TRANSCRIPT                        auto-scroll  │
│ ─────────────────────────────────────────────────── │
│  [Turn 1] AI: "Hi there, sorry to bother you..."   │
│  [Turn 2] REP: "Hey! I'm with BugShield Pro and..." │
│  [Turn 3] AI: "We're already happy with our service"│
│  [Turn 4] REP: "I totally understand, a lot of..."  │
│  ▌ AI is responding...         (blinking cursor)    │
│                                                     │
│ STAGE PROGRESS                                      │
│ ●───●───●───○───○                                   │
│ Open  Pitch  Obj  Close  Done                       │
└─────────────────────────────────────────────────────┘
```

**Behavior:**
- Poll `fetchLiveTranscript` every 3 seconds
- Auto-scroll to the bottom of the transcript as new turns arrive (using `useRef` + `scrollIntoView`)
- Show a blinking cursor indicator when the last turn was from the rep (AI is computing response)
- Stage progress bar updates as the stage_timeline advances
- If session ends (rep disconnects or scenario completes), show "Session Ended" state with a button to "View Full Scorecard →" that navigates to the replay page

**Speaker styling:**
- Rep turns: right-aligned, forest green background `rgba(45, 90, 61, 0.12)`, rounded-2xl
- AI turns: left-aligned, white/40 glassmorphism, rounded-2xl

---

## Part 5: Frontend — Feed Page Auto-Refresh on Session Complete

In `ManagerFeedPage.tsx`, when an SSE event shows a session transitioning from `active` to no longer in the live list (session ended), dispatch a feed refresh event.

Already exists in the codebase: the feed listens for `window.dispatchEvent(new CustomEvent("doordrill:feed-refresh"))`. Use this hook.

---

## Part 6: Notification Dot on Sidebar

In `Sidebar.tsx`, show a red notification dot on the "Feed" nav item when live sessions exist.

- Fetch `fetchLiveSessions` once on mount inside `Sidebar.tsx` with a `setInterval` every 30 seconds
- If `live_sessions.length > 0`, render a `●` pulsing dot next to "Feed"
- Count badge if more than 1: `2` badge number in red circle

---

## Acceptance Criteria

- [ ] `GET /manager/sessions/live` returns accurate live session list
- [ ] SSE stream at `/manager/sessions/live/stream` emits updates every 5s
- [ ] `GET /manager/sessions/:id/live-transcript` returns current partial transcript
- [ ] ManagerFeedPage shows LIVE NOW banner with pulsing dot when sessions are active
- [ ] Elapsed time ticks up live in the banner
- [ ] "Watch Live" navigates to LiveSessionPage
- [ ] LiveSessionPage auto-scrolls transcript, shows blinking cursor, updates stage progress
- [ ] Session end state correctly appears and links to replay
- [ ] Sidebar shows notification dot when live sessions exist
- [ ] SSE EventSource is cleaned up on component unmount (no memory leaks)
- [ ] No TypeScript errors
