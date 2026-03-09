# DoorDrill — Push Notifications PRD
# Phases PN1–PN5

> Paste BOOTSTRAP_PROMPT.md before each phase in Codex.

---

## Context & Audit Findings

Current state (audited 2026-03-09):

- `DeviceToken` model exists (`user_id`, `platform`, `provider`, `token`, `status`, `last_seen_at`)
- `register_device_token()` and `DELETE /rep/device-tokens/{token_id}` endpoints exist in `backend/app/api/rep.py`
- `ExpoPushProvider` and `FcmPushProvider` exist in `notification_providers.py`
- `NotificationDelivery` model with retry logic exists
- **ONLY ONE notification method exists**: `notify_manager_session_completed()` — no rep-facing notifications at all
- **Mobile app has zero push notification code** — `expo-notifications` is not installed, `LoginScreen` never requests push permission, no device token registration flow

Gap: the entire rep notification layer is missing. Infrastructure (DB, providers) is partially ready but the event wiring, rep-facing methods, and mobile integration are absent.

---

## Phase PN1 — Install expo-notifications + Mobile Device Token Registration

### Goal
Wire push permission request and device token registration into the mobile app on login. After this phase, every rep who logs in will have a valid device token in the DB.

### Backend audit required before coding
Read:
- `backend/app/api/rep.py` — confirm `POST /rep/device-tokens` shape: `{ token: string, platform: "ios" | "android", provider: "expo" | "fcm" }`
- `backend/app/models/device_token.py` — confirm fields and unique constraint
- `mobile/src/services/api.ts` — check if `registerDeviceToken()` call exists; it likely does not

### What to build

**Mobile: install dependency**
```
npx expo install expo-notifications expo-device
```

**Mobile: `src/services/notifications.ts` (new file)**
```typescript
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Platform } from "react-native";
import { registerDeviceToken } from "./api";

export async function requestAndRegisterPushToken(): Promise<void> {
  if (!Device.isDevice) return; // skip simulator

  const { status: existing } = await Notifications.getPermissionsAsync();
  let finalStatus = existing;

  if (existing !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== "granted") return; // user denied — soft fail, don't nag

  const token = (
    await Notifications.getExpoPushTokenAsync({
      projectId: process.env.EXPO_PUBLIC_PROJECT_ID, // must be set in .env
    })
  ).data;

  const platform = Platform.OS as "ios" | "android";
  await registerDeviceToken({ token, platform, provider: "expo" });
}

// Configure foreground notification behavior
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});
```

**Mobile: `src/services/api.ts` — add `registerDeviceToken()`**
```typescript
export async function registerDeviceToken(payload: {
  token: string;
  platform: "ios" | "android";
  provider: "expo" | "fcm";
}): Promise<void> {
  await apiPost("/rep/device-tokens", payload);
}
```

**Mobile: `src/screens/LoginScreen.tsx` — call after successful login**
After `setRepId(rep.id)` / `setSession(...)`, add:
```typescript
import { requestAndRegisterPushToken } from "../services/notifications";
// After login success:
void requestAndRegisterPushToken(); // fire-and-forget, don't block login UX
```

**Mobile: `app.json` — add notification permissions**
```json
{
  "expo": {
    "plugins": [
      [
        "expo-notifications",
        {
          "icon": "./assets/notification-icon.png",
          "color": "#2D5A3D",
          "sounds": [],
          "mode": "production"
        }
      ]
    ]
  }
}
```

**Backend: `backend/app/api/rep.py` — confirm `last_seen_at` is updated on duplicate token upsert**
The `register_device_token()` handler should UPSERT (on conflict user_id+provider+token → update `last_seen_at`, keep `status=active`). Verify this is the behavior and add if missing:
```python
# In register_device_token handler, after INSERT:
stmt = insert(DeviceToken).values(**token_data)
stmt = stmt.on_conflict_do_update(
    index_elements=["user_id", "provider", "token"],
    set_={"last_seen_at": func.now(), "status": "active"},
)
await db.execute(stmt)
await db.commit()
```

### Verification
- Simulator shows no push token (skip silently) ✓
- Real device: permission dialog appears on first login
- DB: `device_tokens` row exists with correct `user_id` and `status=active`
- Second login: no duplicate row, `last_seen_at` updated
- TypeScript: no `any` types introduced

---

## Phase PN2 — Backend Rep Notification Methods

### Goal
Build the full suite of rep-facing notification methods in `notification_service.py`. After this phase, the backend can send any rep-facing push notification; nothing is wired to events yet — that's PN3.

### Backend audit required before coding
Read:
- `backend/app/services/notification_service.py` — full file, understand `notify_manager_session_completed()` pattern (get active tokens → build payload → for each token → provider.send() → log delivery)
- `backend/app/models/` — confirm `assignments`, `sessions`, `grading_results`/`scorecards` table structure
- `backend/app/services/notification_providers.py` — confirm `ExpoPushProvider.send(token, title, body, data)` signature

### What to build

Add the following methods to `NotificationService`. Each follows the same pattern as `notify_manager_session_completed()`: look up active device tokens for the user, build a platform-appropriate payload, send via provider, log to `notification_deliveries`.

```python
# ──────────────────────────────────────────────────
# 1. Score ready — sent when grading completes
# ──────────────────────────────────────────────────
async def notify_rep_score_ready(
    self,
    rep_id: str,
    session_id: str,
    scenario_name: str,
    overall_score: float,
) -> None:
    """Push to rep when their drill scorecard is graded and ready."""
    tokens = await self._get_active_tokens(rep_id)
    if not tokens:
        return

    score_display = f"{overall_score:.1f}/10"
    emoji = "🟢" if overall_score >= 8 else "🟡" if overall_score >= 5 else "🔴"
    title = f"{emoji} Drill Results Ready"
    body = f"You scored {score_display} on {scenario_name}. Tap to review."
    data = {"type": "score_ready", "session_id": session_id}

    await self._send_to_tokens(tokens, title, body, data, rep_id)

# ──────────────────────────────────────────────────
# 2. Assignment created — sent when manager assigns drill
# ──────────────────────────────────────────────────
async def notify_rep_assignment_created(
    self,
    rep_id: str,
    assignment_id: str,
    scenario_name: str,
    due_at: datetime | None,
) -> None:
    """Push to rep when a new drill is assigned."""
    tokens = await self._get_active_tokens(rep_id)
    if not tokens:
        return

    title = "📋 New Drill Assigned"
    due_str = f" Due {due_at.strftime('%b %-d')}." if due_at else ""
    body = f"{scenario_name} has been assigned to you.{due_str}"
    data = {"type": "assignment_created", "assignment_id": assignment_id}

    await self._send_to_tokens(tokens, title, body, data, rep_id)

# ──────────────────────────────────────────────────
# 3. Assignment due soon — sent 24h before due_at
# ──────────────────────────────────────────────────
async def notify_rep_assignment_due_soon(
    self,
    rep_id: str,
    assignment_id: str,
    scenario_name: str,
    due_at: datetime,
) -> None:
    """Push to rep 24h before assignment deadline."""
    tokens = await self._get_active_tokens(rep_id)
    if not tokens:
        return

    title = "⏰ Drill Due Tomorrow"
    body = f"'{scenario_name}' is due {due_at.strftime('%b %-d at %-I%p')}. Get it done!"
    data = {"type": "assignment_due_soon", "assignment_id": assignment_id}

    await self._send_to_tokens(tokens, title, body, data, rep_id)

# ──────────────────────────────────────────────────
# 4. Coaching note posted — sent when manager leaves note
# ──────────────────────────────────────────────────
async def notify_rep_coaching_note(
    self,
    rep_id: str,
    session_id: str,
    manager_name: str,
    note_preview: str,  # first 80 chars of note
) -> None:
    """Push to rep when manager leaves a coaching note on their session."""
    tokens = await self._get_active_tokens(rep_id)
    if not tokens:
        return

    title = f"💬 Note from {manager_name}"
    body = note_preview[:80] + ("…" if len(note_preview) > 80 else "")
    data = {"type": "coaching_note", "session_id": session_id}

    await self._send_to_tokens(tokens, title, body, data, rep_id)

# ──────────────────────────────────────────────────
# 5. Streak nudge — sent when rep hasn't drilled in N days
# ──────────────────────────────────────────────────
async def notify_rep_streak_nudge(
    self,
    rep_id: str,
    days_inactive: int,
    last_score: float | None,
) -> None:
    """Nudge rep when they haven't drilled in 2+ days."""
    tokens = await self._get_active_tokens(rep_id)
    if not tokens:
        return

    title = "🔥 Keep Your Streak Going"
    if last_score and last_score < 7.0:
        body = f"You haven't drilled in {days_inactive} days. Your last score was {last_score:.1f} — there's room to improve!"
    else:
        body = f"You haven't drilled in {days_inactive} days. Stay sharp — run a quick drill today."
    data = {"type": "streak_nudge"}

    await self._send_to_tokens(tokens, title, body, data, rep_id)
```

**Private helper (add if not already present):**
```python
async def _get_active_tokens(self, user_id: str) -> list[DeviceToken]:
    result = await self.db.execute(
        select(DeviceToken).where(
            DeviceToken.user_id == user_id,
            DeviceToken.status == "active",
        )
    )
    return result.scalars().all()

async def _send_to_tokens(
    self,
    tokens: list[DeviceToken],
    title: str,
    body: str,
    data: dict,
    user_id: str,
) -> None:
    for token in tokens:
        provider = self._get_provider(token.provider)
        try:
            await provider.send(token.token, title, body, data)
            await self._log_delivery(token, title, body, data, "sent")
        except Exception as exc:
            await self._log_delivery(token, title, body, data, "failed", str(exc))
```

### Verification
- All 5 methods have correct return type `None`
- No `any` types; `datetime | None` union used correctly
- `_get_active_tokens` and `_send_to_tokens` extracted as helpers (no duplication)
- `notify_manager_session_completed` still works (no regression)
- Unit tests: mock `_get_active_tokens` returning empty list → no send; mock returning 1 token → provider called once

---

## Phase PN3 — Wire Notifications to Event Triggers

### Goal
Connect the PN2 notification methods to actual system events: grading completion, assignment creation, assignment due-soon scheduler, and coaching note posting. After this phase, reps receive real-time push notifications at the right moments.

### Backend audit required before coding
Read:
- `backend/app/workers/celery_tasks.py` (or `tasks.py`) — find where grading completes and scorecard is written; this is where `notify_rep_score_ready` fires
- `backend/app/routers/manager.py` — find `POST /manager/assignments` (assignment creation) and `POST /manager/scorecards/:id/coaching-notes` (coaching note)
- `backend/app/services/session_postprocess_service.py` — understand the end-of-session pipeline
- `backend/app/workers/` or `backend/app/services/` — check if a periodic task runner (Celery Beat) is configured for due-soon reminders

### What to wire

**1. Score ready — in Celery grading task**

In the Celery task that calls `grading_service.grade_session()` and persists the scorecard, after successful write:
```python
# After scorecard persisted:
notification_svc = NotificationService(db)
await notification_svc.notify_rep_score_ready(
    rep_id=session.rep_id,
    session_id=session.session_id,
    scenario_name=scenario.name,
    overall_score=scorecard.overall_score,
)
```
Use `asyncio.run()` or an async Celery worker pattern if the task is sync.

**2. Assignment created — in manager router**

In `POST /manager/assignments` (or wherever `Assignment` is created), after DB commit:
```python
notification_svc = NotificationService(db)
await notification_svc.notify_rep_assignment_created(
    rep_id=assignment.rep_id,
    assignment_id=str(assignment.id),
    scenario_name=scenario.name,
    due_at=assignment.due_at,
)
```

**3. Coaching note — in manager router**

In `POST /manager/scorecards/:id/coaching-notes`, after note is persisted:
```python
# Look up which rep owns this session
rep_id = session.rep_id
manager_name = f"{manager.first_name} {manager.last_name}"
notification_svc = NotificationService(db)
await notification_svc.notify_rep_coaching_note(
    rep_id=rep_id,
    session_id=session_id,
    manager_name=manager_name,
    note_preview=note.note,
)
```

**4. Assignment due soon — Celery Beat periodic task (new)**

Add to Celery Beat schedule (e.g., `celeryconfig.py` or `celery_app.py`):
```python
from celery.schedules import crontab

beat_schedule = {
    "assignment-due-soon-reminders": {
        "task": "app.workers.tasks.send_assignment_due_soon_reminders",
        "schedule": crontab(minute=0, hour="*/1"),  # every hour
    },
}
```

New Celery task `send_assignment_due_soon_reminders`:
```python
@celery_app.task
def send_assignment_due_soon_reminders():
    """Find assignments due in 20-28 hours and notify reps (24h window, idempotent)."""
    async def _run():
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            window_start = now + timedelta(hours=20)
            window_end = now + timedelta(hours=28)

            result = await db.execute(
                select(Assignment, Rep, Scenario)
                .join(Rep, Assignment.rep_id == Rep.id)
                .join(Scenario, Assignment.scenario_id == Scenario.id)
                .where(
                    Assignment.due_at.between(window_start, window_end),
                    Assignment.status == "pending",
                    Assignment.due_soon_notified_at.is_(None),  # idempotency
                )
            )
            rows = result.all()

            notification_svc = NotificationService(db)
            for assignment, rep, scenario in rows:
                await notification_svc.notify_rep_assignment_due_soon(
                    rep_id=str(rep.id),
                    assignment_id=str(assignment.id),
                    scenario_name=scenario.name,
                    due_at=assignment.due_at,
                )
                assignment.due_soon_notified_at = now  # mark sent
            await db.commit()

    asyncio.run(_run())
```

**Migration needed:** add `due_soon_notified_at TIMESTAMPTZ NULL` to `assignments` table.

**5. Streak nudge — Celery Beat daily task (new)**

```python
beat_schedule["streak-nudges"] = {
    "task": "app.workers.tasks.send_streak_nudges",
    "schedule": crontab(minute=0, hour=18),  # 6pm daily
}
```

```python
@celery_app.task
def send_streak_nudges():
    """Notify reps inactive for 2, 4, or 7 days (configurable thresholds)."""
    NUDGE_DAYS = [2, 4, 7]

    async def _run():
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            notification_svc = NotificationService(db)

            for days in NUDGE_DAYS:
                cutoff = now - timedelta(days=days)
                prev_cutoff = now - timedelta(days=days + 1)

                # Reps whose last session was exactly `days` days ago
                result = await db.execute(
                    select(Rep, func.max(Session.started_at).label("last_drill"))
                    .join(Session, Session.rep_id == Rep.id)
                    .group_by(Rep.id)
                    .having(
                        func.max(Session.started_at).between(prev_cutoff, cutoff)
                    )
                )
                for rep, last_drill in result.all():
                    last_score = await _get_last_score(db, rep.id)
                    await notification_svc.notify_rep_streak_nudge(
                        rep_id=str(rep.id),
                        days_inactive=days,
                        last_score=last_score,
                    )

    asyncio.run(_run())
```

### Verification
- Grading task: after grade, `notify_rep_score_ready` called with correct args
- Manager assignment route: push fires, rep device token lookup uses correct `rep_id`
- Coaching note route: `manager_name` resolved from JWT, not hardcoded
- Celery Beat: `send_assignment_due_soon_reminders` runs hourly; idempotent (won't double-send)
- Streak nudge: only reps with activity in past, not all-time inactive reps (no spam on fresh DB)
- All async DB calls wrapped properly in async context managers

---

## Phase PN4 — Mobile Notification Deep Linking

### Goal
Handle incoming push notifications in the mobile app and deep-link the rep to the correct screen (ScoreScreen for score_ready, AssignmentsScreen for assignment_created/due_soon, ScoreScreen for coaching_note). After this phase, tapping a notification lands the rep exactly where they need to be.

### Mobile audit required before coding
Read:
- `mobile/src/navigation/types.ts` — confirm `RootStackParamList` shape and which screens accept which params
- `mobile/src/navigation/` (RootNavigator or AppNavigator) — understand how navigation ref is set up
- `mobile/src/App.tsx` — check if `NavigationContainer` ref is accessible from outside

### What to build

**`src/services/notifications.ts` — add deep link handler**
```typescript
import { createNavigationContainerRef } from "@react-navigation/native";
import { RootStackParamList } from "../navigation/types";
import * as Notifications from "expo-notifications";

export const navigationRef = createNavigationContainerRef<RootStackParamList>();

export function setupNotificationResponseListener(): () => void {
  const subscription = Notifications.addNotificationResponseReceivedListener(
    (response) => {
      const data = response.notification.request.content.data as Record<string, string>;
      const type = data?.type;

      if (!navigationRef.isReady()) return;

      switch (type) {
        case "score_ready":
        case "coaching_note":
          if (data.session_id) {
            navigationRef.navigate("Score", { sessionId: data.session_id });
          }
          break;
        case "assignment_created":
        case "assignment_due_soon":
          navigationRef.navigate("MainTabs", { screen: "AssignmentsTab" });
          break;
        default:
          break;
      }
    }
  );

  return () => subscription.remove();
}
```

**`src/App.tsx` (or root Navigator file) — wire ref and listener**
```typescript
import { navigationRef, setupNotificationResponseListener } from "./services/notifications";

// In the root component:
useEffect(() => {
  const cleanup = setupNotificationResponseListener();
  return cleanup;
}, []);

// On NavigationContainer:
<NavigationContainer ref={navigationRef}>
  {/* ... */}
</NavigationContainer>
```

**Handle notification received while app is in foreground:**
```typescript
// In App.tsx useEffect:
const foregroundSub = Notifications.addNotificationReceivedListener((notification) => {
  // Optional: show in-app toast/banner instead of system notification
  const data = notification.request.content.data as Record<string, string>;
  if (data.type === "score_ready") {
    // Could trigger a small in-app banner component
  }
});
return () => {
  foregroundSub.remove();
  cleanup();
};
```

**`mobile/src/navigation/types.ts` — ensure AssignmentsTab is in BottomTabParamList**
```typescript
export type BottomTabParamList = {
  HomeTab: undefined;
  AssignmentsTab: undefined;
  HistoryTab: undefined;
  ProfileTab: undefined;
};
```

### Verification
- Cold launch from notification: app opens to correct screen
- Background launch: same deep link behavior
- Foreground: system notification shown (per `setNotificationHandler`)
- Unknown notification types: handled gracefully (no crash)
- Navigation ref not ready: guarded, no crash

---

## Phase PN5 — Notification Preferences Screen + Token Cleanup

### Goal
Give reps control over which notifications they receive. Add a Preferences section in ProfileScreen with per-type toggles. Also add a token cleanup endpoint (device revoked on logout) so stale tokens don't accumulate and skew delivery. After this phase, the notification system is production-complete.

### What to build

**Backend: `backend/app/api/rep.py` — logout endpoint revokes token**

The `DELETE /rep/device-tokens/{token_id}` endpoint already exists. Ensure the mobile logout flow calls it.

Add `PUT /rep/notification-preferences` endpoint:
```python
class NotificationPreferences(BaseModel):
    score_ready: bool = True
    assignment_created: bool = True
    assignment_due_soon: bool = True
    coaching_note: bool = True
    streak_nudge: bool = True

@router.put("/notification-preferences")
async def update_notification_preferences(
    prefs: NotificationPreferences,
    rep: Rep = Depends(get_current_rep),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferences:
    rep.notification_preferences = prefs.model_dump()
    await db.commit()
    return prefs
```

Add `notification_preferences JSONB NOT NULL DEFAULT '{}'` column to `reps` table (migration).

**Backend: check preferences before sending**

In `NotificationService._send_to_tokens()` or each individual method, gate on preferences:
```python
async def _is_notif_enabled(self, user_id: str, notif_type: str) -> bool:
    rep = await self.db.get(Rep, user_id)
    prefs = rep.notification_preferences or {}
    return prefs.get(notif_type, True)  # default True if not set
```

Call at top of each `notify_rep_*` method:
```python
if not await self._is_notif_enabled(rep_id, "score_ready"):
    return
```

**Mobile: `src/screens/ProfileScreen.tsx` — add Notification Preferences section**

Add a new collapsible section below the existing profile content:

```tsx
import { Switch } from "react-native";

// State
const [prefs, setPrefs] = useState({
  score_ready: true,
  assignment_created: true,
  assignment_due_soon: true,
  coaching_note: true,
  streak_nudge: true,
});

const togglePref = async (key: keyof typeof prefs) => {
  const updated = { ...prefs, [key]: !prefs[key] };
  setPrefs(updated);
  try {
    await updateNotificationPreferences(updated);
  } catch {
    setPrefs(prefs); // revert on failure
  }
};

// In render — after existing profile content:
<View style={styles.prefsSection}>
  <Text style={styles.prefsSectionTitle}>Notifications</Text>
  {[
    { key: "score_ready" as const, label: "Score Ready", desc: "When your drill is graded" },
    { key: "assignment_created" as const, label: "New Assignment", desc: "When a drill is assigned to you" },
    { key: "assignment_due_soon" as const, label: "Due Reminders", desc: "24h before deadline" },
    { key: "coaching_note" as const, label: "Coaching Notes", desc: "When your manager leaves feedback" },
    { key: "streak_nudge" as const, label: "Practice Reminders", desc: "When you haven't drilled in 2+ days" },
  ].map(({ key, label, desc }) => (
    <View key={key} style={styles.prefRow}>
      <View style={styles.prefTextGroup}>
        <Text style={styles.prefLabel}>{label}</Text>
        <Text style={styles.prefDesc}>{desc}</Text>
      </View>
      <Switch
        value={prefs[key]}
        onValueChange={() => togglePref(key)}
        trackColor={{ false: colors.line, true: colors.accent }}
        thumbColor="#FFFFFF"
      />
    </View>
  ))}
</View>
```

**Mobile: load preferences on mount**
```typescript
// In ProfileScreen useEffect:
const savedPrefs = await fetchNotificationPreferences();
if (savedPrefs) setPrefs(savedPrefs);
```

**Mobile: revoke token on logout**
```typescript
// In logout handler (wherever logout is triggered):
import { getStoredPushToken } from "../services/notifications";
const tokenId = await getStoredPushToken();
if (tokenId) {
  await revokeDeviceToken(tokenId);
}
```

**`src/services/notifications.ts` — store token ID after registration**
```typescript
import AsyncStorage from "@react-native-async-storage/async-storage";
// After registerDeviceToken() succeeds, store the returned token row ID:
await AsyncStorage.setItem("push_token_id", registeredToken.id);

export async function getStoredPushToken(): Promise<string | null> {
  return AsyncStorage.getItem("push_token_id");
}
```

### Verification
- Rep can toggle each notification type; preference persists across app restarts
- Backend: notification method skips send when preference disabled
- Logout: device token row status set to `revoked`, no further pushes delivered
- Default state: all preferences true for new reps (no DB row → defaults to enabled)
- Stale token (app uninstalled/reinstalled): Expo push API returns `DeviceNotRegistered` error → token marked `revoked` in `_send_to_tokens` error handler

---

## Summary: What PN1–PN5 Delivers

| Phase | Deliverable |
|-------|-------------|
| PN1 | expo-notifications installed, push permission requested on login, device token registered in DB |
| PN2 | 5 rep-facing notification methods: score ready, assignment created, due soon, coaching note, streak nudge |
| PN3 | Events wired: grading task, assignment route, coaching note route, Celery Beat for due-soon + streak |
| PN4 | Deep linking: tap notification → land on correct screen (Score, Assignments) |
| PN5 | Notification preferences in ProfileScreen + token revocation on logout |

After PN5, the push notification system is fully production-ready: reps get notified, can control what they receive, and the system doesn't leak stale tokens.
