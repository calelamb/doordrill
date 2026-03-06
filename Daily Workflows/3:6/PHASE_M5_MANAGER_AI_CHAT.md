# PHASE M5 — Manager AI Chat
# Goal: A manager should be able to ask any question about their team in plain English
# and get a precise, data-backed answer in seconds. This is the product moat —
# no other training tool lets you query your team's performance like a conversation.

---

## Files to read first (required before touching anything)

- `backend/app/routers/manager.py` — all existing endpoints, understand data available
- `backend/app/services/grading.py` — how Claude is called, follow the same pattern
- `dashboard/src/lib/types.ts` — all data shapes
- `dashboard/src/lib/api.ts` — all fetch functions
- `dashboard/src/components/Sidebar.tsx` — where the chat trigger button lives
- `dashboard/src/pages/AnalyticsPage.tsx` — for context on data model

---

## Part 1: Backend — AI Chat Endpoint

### New endpoint: POST /manager/ai/chat

This is the core endpoint. It accepts a natural language question and returns a structured answer with supporting data.

**Request body:**
```python
class ManagerChatRequest(BaseModel):
    manager_id: str
    message: str
    conversation_history: List[Dict[str, str]] = []  # [{role: "user"|"assistant", content: "..."}]
    period_days: int = 30
```

**Logic:**

Step 1 — Intent Classification: Call Claude with a lightweight prompt to classify what data is needed:
```
You are classifying a manager's question about their sales training data.
Question: "{message}"

Respond with JSON only:
{
  "intent": one of ["team_performance", "rep_specific", "scenario_analysis", "coaching_effectiveness", "risk_alerts", "comparison", "general"],
  "rep_name_mentioned": string | null,  // if they mention a specific rep
  "scenario_mentioned": string | null,
  "category_mentioned": string | null   // opening, pitch, objection, closing, professionalism
}
```

Step 2 — Data Gathering: Based on intent, query the relevant data:
- `team_performance` → fetch `CommandCenterResponse`
- `rep_specific` → fetch `RepProgress` for the mentioned rep (fuzzy match rep name)
- `scenario_analysis` → fetch `ScenarioIntelligenceResponse`
- `coaching_effectiveness` → fetch `CoachingAnalyticsResponse`
- `risk_alerts` → fetch `RepRiskDetailResponse` (from Phase M3 endpoint)
- `comparison` → fetch both `CommandCenterResponse` and `RepProgress` for all reps

Step 3 — Answer Generation: Call Claude with the actual data + conversation history:
```
You are an expert sales performance analyst for DoorDrill, a D2D sales training platform.
You are answering a manager's question about their team's training performance.

Team data (last {period_days} days):
{serialized_relevant_data}

Conversation history:
{conversation_history}

Manager's question: "{message}"

Respond with JSON:
{
  "answer": "your natural language answer (2-4 sentences, direct and specific)",
  "key_metric": "the single most relevant number or stat that answers the question (e.g. '6.2 avg score')",
  "key_metric_label": "label for the metric (e.g. 'Team Average Score')",
  "follow_up_suggestions": ["2-3 follow-up questions the manager might want to ask next"],
  "action_suggestion": "a concrete action the manager should take (1 sentence, optional, can be null)",
  "data_points": [{"label": "stat name", "value": "stat value"}]  // max 4 supporting data points
}
```

Step 4 — Return structured response with both the answer and the supporting data used.

**Response schema:**
```python
class ChatDataPoint(BaseModel):
    label: str
    value: str

class ManagerChatResponse(BaseModel):
    answer: str
    key_metric: str | None
    key_metric_label: str | None
    follow_up_suggestions: List[str]
    action_suggestion: str | None
    data_points: List[ChatDataPoint]
    intent_detected: str
    sources_used: List[str]  # which endpoints were queried
```

**Performance:** The two Claude calls (classify + answer) should complete in < 4 seconds total. Use `claude-haiku-3` for classification (fast + cheap) and `claude-opus` or `claude-sonnet` for the answer generation.

---

## Part 2: Frontend — Types

Add to `dashboard/src/lib/types.ts`:

```typescript
export type ChatDataPoint = {
  label: string;
  value: string;
};

export type ManagerChatResponse = {
  answer: string;
  key_metric: string | null;
  key_metric_label: string | null;
  follow_up_suggestions: string[];
  action_suggestion: string | null;
  data_points: ChatDataPoint[];
  intent_detected: string;
  sources_used: string[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ManagerChatResponse;  // only on assistant messages
  timestamp: string;
};
```

Add to `dashboard/src/lib/api.ts`:

```typescript
export async function sendManagerChatMessage(
  managerId: string,
  message: string,
  history: Array<{ role: "user" | "assistant"; content: string }>,
  periodDays = 30
): Promise<ManagerChatResponse> {
  return requestJson<ManagerChatResponse>(
    `/manager/ai/chat`,
    {
      method: "POST",
      body: JSON.stringify({
        manager_id: managerId,
        message,
        conversation_history: history,
        period_days: periodDays,
      }),
    },
    { userId: managerId, role: "manager" }
  );
}
```

---

## Part 3: Frontend — Chat Panel Component

Create `dashboard/src/components/ManagerChatPanel.tsx`.

This is a slide-over panel that appears from the right side when triggered. It does NOT navigate to a new page — it overlays on top of the current view so managers can ask questions while looking at data.

**Trigger:** A floating "Ask AI" button fixed to the bottom-right of all manager pages, rendered inside `ProtectedLayout` in `App.tsx` (so it persists across pages).

**Button design:**
```
          ╭─────────────╮
          │  ✦ Ask AI   │
          ╰─────────────╯
```
- Position: `fixed bottom-6 right-6 z-50`
- Background: forest green `#2D5A3D`
- Text: white, 14px, "✦ Ask AI"
- Pulse animation when a new insight is available (optional, skip if complex)
- On click: opens the chat slide-over panel

**Panel design:**
```
┌───────────────────────────────────────────┐
│ ✦ Ask your data                       [×] │
│ ─────────────────────────────────────── │
│                                           │
│  [User message bubble]                    │
│              [AI response card]           │
│                                           │
│  ┌─ AI Response ──────────────────────┐  │
│  │ Jordan's objection rate improved   │  │
│  │ 18% after you added coaching notes │  │
│  │                                     │  │
│  │ 📊 +18%  Objection Improvement     │  │
│  │                                     │  │
│  │ Supporting data:                    │  │
│  │ • Before: 4.8  • After: 5.7        │  │
│  │ • 3 coached sessions               │  │
│  │                                     │  │
│  │ 💡 Assign a follow-up drill now    │  │
│  │                                     │  │
│  │ Try asking:                         │  │
│  │ "Who else needs objection work?"   │  │
│  │ "What scenario targets objections?"│  │
│  └─────────────────────────────────────┘  │
│                                           │
│ ─────────────────────────────────────── │
│ [Ask anything about your team...    ] [→]│
└───────────────────────────────────────────┘
```

**Panel specs:**
- Width: 420px on desktop, full-screen on mobile
- Slides in from the right with Framer Motion: `x: 420 → 0, opacity: 0 → 1, duration: 0.3`
- Background: `bg-white/80 backdrop-blur-2xl border-l border-white/30`
- Maintains conversation history across open/close cycles (stored in component state or localStorage)
- Max 20 messages before suggesting "Start new conversation"

**Message bubbles:**
- User messages: right-aligned, forest green background, white text, `rounded-2xl rounded-br-sm`
- AI response cards: left-aligned, white/50 glassmorphism, `rounded-2xl rounded-bl-sm`

**AI response card internal layout:**
1. Main answer text (body/14px, primary ink color)
2. Key metric highlighted: large number + label in a green pill
3. Data points: compact grid, 2 columns, label/value pairs
4. Action suggestion: amber-tinted card with 💡 icon, clickable if it suggests a navigation action
5. Follow-up suggestions: 2-3 pill buttons the manager can click to instantly send that question

**Follow-up suggestion clicks:**
- Clicking a suggestion pill immediately submits it as the next message (no need to type)

**Loading state:**
- While waiting for response: show a typing indicator (3 animated dots) in an AI bubble
- Disable the input and send button while loading

**Error state:**
- On API failure: show "Couldn't reach the AI. Try again." in an error-styled bubble with a retry button

---

## Part 4: Frontend — Keyboard Shortcut

Add a global keyboard shortcut: `Cmd+K` (Mac) / `Ctrl+K` (Windows) to open/close the chat panel.

In `App.tsx` inside `ProtectedLayout`:
```tsx
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setChatOpen(prev => !prev);
    }
  };
  window.addEventListener("keydown", handler);
  return () => window.removeEventListener("keydown", handler);
}, []);
```

Add a tooltip to the "Ask AI" button: `⌘K` on Mac, `Ctrl+K` on Windows.

---

## Part 5: Suggested Starter Questions

When the chat panel is opened for the first time (empty conversation), show a grid of suggested starter questions the manager can click:

```
┌──────────────────────────────────────────────┐
│ ✦ Ask your data                              │
│                                              │
│ Try asking...                                │
│                                              │
│ ╭──────────────────╮  ╭──────────────────╮  │
│ │Who's at risk this│  │Which scenario is │  │
│ │ week?            │  │hardest for my    │  │
│ │                  │  │team?             │  │
│ ╰──────────────────╯  ╰──────────────────╯  │
│                                              │
│ ╭──────────────────╮  ╭──────────────────╮  │
│ │How did Jordan    │  │What should I     │  │
│ │ improve last     │  │focus coaching on │  │
│ │ month?           │  │this week?        │  │
│ ╰──────────────────╯  ╰──────────────────╯  │
└──────────────────────────────────────────────┘
```

Clicking any suggestion sends it as the first message.

---

## Acceptance Criteria

- [ ] `POST /manager/ai/chat` correctly classifies intent and queries the right data
- [ ] Response includes `answer`, `key_metric`, `data_points`, `follow_up_suggestions`
- [ ] Classification uses claude-haiku (fast), answer uses claude-sonnet (quality)
- [ ] Chat panel slides in/out smoothly with Framer Motion
- [ ] "Ask AI" button is visible on all manager pages (rendered in ProtectedLayout)
- [ ] `Cmd+K` / `Ctrl+K` opens and closes the panel
- [ ] Conversation history persists during panel open/close cycles within the same session
- [ ] Follow-up suggestion pills send the question when clicked
- [ ] Typing indicator appears while waiting for response
- [ ] Action suggestion cards are clickable and navigate correctly
- [ ] Starter questions appear on empty conversation
- [ ] No TypeScript errors
- [ ] Panel handles API errors gracefully with retry option
