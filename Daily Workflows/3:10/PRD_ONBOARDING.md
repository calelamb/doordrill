# DoorDrill — Onboarding PRD
# Phases OB1–OB5

> Paste BOOTSTRAP_PROMPT.md before each phase in Codex.

---

## Context & Audit Findings

Current state (audited 2026-03-09):

**Backend auth — fully implemented, never used by mobile:**
- `POST /auth/login` → email + password → `{ access_token, refresh_token, expires_in, user: { id, org_id, team_id, role, name, email } }`
- `POST /auth/register` → name + email + password + role + org_id/org_name → same response
- `POST /auth/refresh` → refresh_token → new token pair
- `AuthService` hashes passwords (bcrypt), issues JWTs with configurable expiry
- `User` model has `org_id`, `team_id`, `role`, `name`, `email`, `password_hash`, `auth_provider`

**Mobile auth — dev prototype only:**
- `LoginScreen.tsx` calls `lookupRepByEmail(email)` — a fake endpoint that returns `rep_id` without any password check
- No JWT stored in mobile app; API calls use `X-User-Id` mock header
- No onboarding screens, no push permission request on first launch
- No invite-based signup flow
- No first-drill guidance

**Dashboard auth — not audited but assumed working** (managers log into dashboard, create orgs/teams, invite reps).

Gap: everything between "manager signs up" and "rep is drilling" is either missing or mocked. These phases replace the mock with a real, production-quality auth + onboarding funnel.

---

## Phase OB1 — Replace Mock Auth with Real JWT in Mobile

### Goal
Replace `lookupRepByEmail()` with a real call to `POST /auth/login`. Store the JWT in `expo-secure-store` (not AsyncStorage — tokens must be in the secure enclave). Wire `access_token` into all API calls and implement silent token refresh via `POST /auth/refresh`. After this phase, mobile auth is production-ready.

### Mobile audit required before coding
Read:
- `mobile/src/services/api.ts` — understand current API call pattern (does it use Axios interceptors, plain fetch, or a custom wrapper? find where `X-User-Id` is set)
- `mobile/src/store/session.ts` — understand what `repId`, `setRepId`, and `clearSession` currently store
- `mobile/src/navigation/` — understand how auth state gates navigation (is there an `isAuthenticated` check or just a `repId` null check?)

### What to build

**Install dependency:**
```
npx expo install expo-secure-store
```

**`src/store/session.ts` — extend with token storage**

Replace the current `repId`-only store with a proper auth state:
```typescript
import * as SecureStore from "expo-secure-store";
import { create } from "zustand";

const ACCESS_TOKEN_KEY = "dd_access_token";
const REFRESH_TOKEN_KEY = "dd_refresh_token";

interface SessionState {
  repId: string | null;
  userId: string | null;
  orgId: string | null;
  role: "rep" | "manager" | "admin" | null;
  name: string | null;
  isAuthenticated: boolean;
  isFirstLaunch: boolean;
  setSession: (user: AuthUser, tokens: { access: string; refresh: string }) => Promise<void>;
  restoreSession: () => Promise<void>;
  clearSession: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
}

export const useSession = create<SessionState>((set, get) => ({
  repId: null,
  userId: null,
  orgId: null,
  role: null,
  name: null,
  isAuthenticated: false,
  isFirstLaunch: true,

  setSession: async (user, tokens) => {
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, tokens.access);
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, tokens.refresh);
    set({
      repId: user.id,
      userId: user.id,
      orgId: user.org_id,
      role: user.role as SessionState["role"],
      name: user.name,
      isAuthenticated: true,
    });
  },

  restoreSession: async () => {
    const access = await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
    const refresh = await SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
    if (!access || !refresh) return;
    // Attempt refresh to validate token and get fresh user data
    try {
      const result = await refreshTokens(refresh);
      await get().setSession(result.user, { access: result.access_token, refresh: result.refresh_token });
    } catch {
      await get().clearSession();
    }
  },

  clearSession: async () => {
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
    set({ repId: null, userId: null, orgId: null, role: null, name: null, isAuthenticated: false });
  },

  getAccessToken: async () => SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
}));
```

**`src/services/api.ts` — replace X-User-Id with Bearer token**

Refactor the base request helper:
```typescript
import { useSession } from "../store/session";

async function apiRequest<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const token = await useSession.getState().getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    // Token expired — attempt silent refresh
    const refreshed = await attemptSilentRefresh();
    if (refreshed) {
      return apiRequest<T>(method, path, body); // retry once
    }
    await useSession.getState().clearSession(); // logout
    throw new Error("Session expired");
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
  }

  return res.json() as Promise<T>;
}

async function attemptSilentRefresh(): Promise<boolean> {
  const store = useSession.getState();
  const refresh = await SecureStore.getItemAsync("dd_refresh_token");
  if (!refresh) return false;
  try {
    const result = await refreshTokens(refresh);
    await store.setSession(result.user, {
      access: result.access_token,
      refresh: result.refresh_token,
    });
    return true;
  } catch {
    return false;
  }
}
```

**Add auth API methods:**
```typescript
export async function loginWithCredentials(email: string, password: string) {
  return apiPost<AuthTokenResponse>("/auth/login", { email, password });
}

export async function refreshTokens(refreshToken: string) {
  return apiPost<AuthTokenResponse>("/auth/refresh", { refresh_token: refreshToken });
}
```

**`src/screens/LoginScreen.tsx` — replace lookupRepByEmail with real login**
```typescript
import { loginWithCredentials } from "../services/api";
import { useSession } from "../store/session";
import { requestAndRegisterPushToken } from "../services/notifications";

const { setSession } = useSession();

const handleLogin = async () => {
  setLoading(true);
  setError("");
  try {
    const result = await loginWithCredentials(email.trim(), password);
    await setSession(result.user, {
      access: result.access_token,
      refresh: result.refresh_token,
    });
    void requestAndRegisterPushToken(); // fire-and-forget
  } catch (err) {
    setError(err instanceof Error ? err.message : "Invalid email or password");
    setLoading(false);
  }
};
```

**`src/App.tsx` — restore session on app launch**
```typescript
useEffect(() => {
  void useSession.getState().restoreSession();
}, []);
```

**Navigation gating — use `isAuthenticated` instead of `repId`:**
```typescript
const { isAuthenticated } = useSession();
// In navigator:
isAuthenticated ? <MainTabs /> : <LoginScreen />
```

### Types to add to `src/types.ts`
```typescript
export interface AuthUser {
  id: string;
  org_id: string;
  team_id: string | null;
  role: "rep" | "manager" | "admin";
  name: string;
  email: string;
}

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: AuthUser;
}
```

### Verification
- Login with correct credentials: JWT stored in SecureStore, user navigated to MainTabs
- Login with wrong password: 401 → "Invalid email or password" shown, no crash
- Kill app, reopen: session restored silently if refresh token valid
- Expired access token: one silent refresh attempted, then app logs out gracefully
- No `X-User-Id` headers anywhere in codebase after this phase (grep to confirm)
- TypeScript strict: no `any`, all token fields typed

---

## Phase OB2 — Manager Invite Flow (Backend + Email)

### Goal
Managers invite reps by email from the dashboard. The rep receives an email with an invitation link containing a short-lived token. Tapping the link deep-links into the app to a pre-filled registration screen. After this phase, reps can join without a manager manually creating accounts for them.

### Backend audit required before coding
Read:
- `backend/app/models/user.py` — confirm `User`, `Organization`, `Team` model fields
- `backend/app/api/auth.py` — understand existing `POST /auth/register` (already accepts `org_id`)
- `backend/app/services/notification_providers.py` — `SendGridEmailProvider` or `SesEmailProvider` for invite email
- Check if an `invitations` table exists: `grep -rn "invitation" backend/app/models/`

### What to build

**New migration: `invitations` table**
```sql
CREATE TABLE invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    team_id UUID REFERENCES teams(id),
    invited_by UUID NOT NULL REFERENCES users(id),
    email TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,  -- 32-char random hex
    role TEXT NOT NULL DEFAULT 'rep',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | expired
    expires_at TIMESTAMPTZ NOT NULL,  -- 7 days
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMPTZ
);
CREATE INDEX ON invitations(token);
CREATE INDEX ON invitations(email, status);
```

**New backend endpoint: `POST /manager/invitations`**
```python
class InviteRepRequest(BaseModel):
    email: EmailStr
    team_id: str | None = None
    role: str = "rep"

class InviteRepResponse(BaseModel):
    invitation_id: str
    email: str
    invite_url: str  # deep link for manager to share manually if needed
    expires_at: datetime

@router.post("/invitations", response_model=InviteRepResponse)
async def invite_rep(
    payload: InviteRepRequest,
    manager: User = Depends(get_current_manager),
    db: AsyncSession = Depends(get_db),
) -> InviteRepResponse:
    token = secrets.token_hex(32)
    expires_at = datetime.utcnow() + timedelta(days=7)

    invitation = Invitation(
        org_id=manager.org_id,
        team_id=payload.team_id or manager.team_id,
        invited_by=manager.id,
        email=payload.email.lower(),
        token=token,
        role=payload.role,
        expires_at=expires_at,
    )
    db.add(invitation)
    await db.commit()

    # Build deep link: doordrill://invite?token=<token>&email=<email>
    invite_url = f"doordrill://invite?token={token}&email={payload.email}"

    # Send email via configured provider
    email_provider = get_email_provider()  # SendGrid/SES/Log
    await email_provider.send(
        to=payload.email,
        subject=f"{manager.name} invited you to DoorDrill",
        body=build_invite_email(manager.name, invite_url, expires_at),
    )

    return InviteRepResponse(
        invitation_id=str(invitation.id),
        email=payload.email,
        invite_url=invite_url,
        expires_at=expires_at,
    )
```

**New backend endpoint: `POST /auth/accept-invite`**
```python
class AcceptInviteRequest(BaseModel):
    token: str
    name: str
    password: str

@router.post("/accept-invite", response_model=AuthTokenResponse)
async def accept_invite(
    payload: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthTokenResponse:
    invitation = await db.scalar(
        select(Invitation).where(
            Invitation.token == payload.token,
            Invitation.status == "pending",
            Invitation.expires_at > datetime.utcnow(),
        )
    )
    if not invitation:
        raise HTTPException(status_code=400, detail="Invitation is invalid or expired")

    # Check if user already exists (re-invite case)
    existing = await db.scalar(select(User).where(User.email == invitation.email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        org_id=invitation.org_id,
        team_id=invitation.team_id,
        role=UserRole(invitation.role),
        name=payload.name,
        email=invitation.email,
        password_hash=auth_service.hash_password(payload.password),
        auth_provider="invite",
    )
    db.add(user)

    invitation.status = "accepted"
    invitation.accepted_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)

    tokens = auth_service.issue_tokens(user)
    return _to_auth_response(user, tokens)
```

**New endpoint: `GET /auth/validate-invite?token=<token>`**
```python
@router.get("/validate-invite")
async def validate_invite(token: str, db: AsyncSession = Depends(get_db)):
    invitation = await db.scalar(
        select(Invitation).where(
            Invitation.token == token,
            Invitation.status == "pending",
            Invitation.expires_at > datetime.utcnow(),
        )
    )
    if not invitation:
        raise HTTPException(status_code=400, detail="Invitation is invalid or expired")
    return {"email": invitation.email, "org_id": str(invitation.org_id), "valid": True}
```

**Mobile: deep link handler + RegisterScreen**

Add URL scheme to `app.json`:
```json
{
  "expo": {
    "scheme": "doordrill"
  }
}
```

In `App.tsx`, handle `doordrill://invite?token=...&email=...` using `expo-linking`:
```typescript
import * as Linking from "expo-linking";

useEffect(() => {
  const sub = Linking.addEventListener("url", ({ url }) => {
    const parsed = Linking.parse(url);
    if (parsed.path === "invite" && parsed.queryParams?.token) {
      navigationRef.navigate("Register", {
        token: parsed.queryParams.token as string,
        email: parsed.queryParams.email as string,
      });
    }
  });
  return () => sub.remove();
}, []);
```

**`src/screens/RegisterScreen.tsx` (new screen):**
```tsx
// Pre-fills email from invite token, accepts name + password
// Calls GET /auth/validate-invite?token=... on mount to verify
// Calls POST /auth/accept-invite on submit
// On success: same flow as login (setSession → MainTabs → push registration)
// Design: same glassmorphism card as LoginScreen, TreePine brand header
// Fields: Full Name, Password, Confirm Password
// Email shown as non-editable label (pulled from invite token)
```

Add `Register` to `RootStackParamList`:
```typescript
Register: { token: string; email: string };
```

### Verification
- Manager POSTs invite → email delivered → invitation row in DB with `status=pending`
- Rep taps link → app opens to RegisterScreen with email pre-filled
- Expired token → error shown ("Invitation has expired — ask your manager to resend")
- Valid registration → JWT issued → user in DB → invitation `status=accepted`
- Second tap on same link → 400 error shown
- TypeScript: no `any`

---

## Phase OB3 — First-Launch Experience (Splash → Onboarding → Push Permission)

### Goal
New reps who install the app and accept an invite see a polished 3-slide onboarding flow before reaching the login/register screen. The flow explains the product, sets expectations, and asks for push notification permission at the right moment (after value is demonstrated, before the first drill). Returning users skip onboarding entirely. After this phase, first impressions are strong and push opt-in rates are high.

### What to build

**`src/screens/OnboardingScreen.tsx` (new screen)**

3-slide pager with skip button. Each slide: full-screen LinearGradient with centered icon, large title, subtitle.

```
Slide 1 — "Train Like It's Real"
  Icon: Mic (32px, accent green)
  Title: "Train Like It's Real"
  Body: "Practice D2D conversations with a lifelike AI homeowner. Get scored, get better."

Slide 2 — "Know Exactly Where You Stand"
  Icon: BarChart2 (32px, accent green)
  Title: "Know Exactly Where You Stand"
  Body: "Detailed scorecards show your strengths and exactly what to work on after every drill."

Slide 3 — "Your Manager Has Your Back"
  Icon: Users (32px, accent green)
  Title: "Your Manager Has Your Back"
  Body: "Get coaching notes, new drills assigned, and reminders — right to your phone."
  CTA: "Get Started" button (navigates to push permission step)
```

After Slide 3 "Get Started" tapped:

```
Push Permission Step (modal-style, same screen):
  Icon: Bell (40px, accent green)
  Title: "Stay in the loop"
  Body: "Get notified when your score is ready, a drill is assigned, or your manager leaves feedback."
  Primary CTA: "Allow Notifications" → calls Notifications.requestPermissionsAsync()
  Secondary CTA: "Not now" → skip, go to LoginScreen

After either choice → navigate to LoginScreen
```

**Skip/seen logic:**
```typescript
import AsyncStorage from "@react-native-async-storage/async-storage";

const ONBOARDING_SEEN_KEY = "dd_onboarding_seen";

export async function hasSeenOnboarding(): Promise<boolean> {
  return (await AsyncStorage.getItem(ONBOARDING_SEEN_KEY)) === "true";
}

export async function markOnboardingComplete(): Promise<void> {
  await AsyncStorage.setItem(ONBOARDING_SEEN_KEY, "true");
}
```

**Navigation guard in `App.tsx`:**
```typescript
const [showOnboarding, setShowOnboarding] = useState<boolean | null>(null);

useEffect(() => {
  hasSeenOnboarding().then((seen) => setShowOnboarding(!seen));
}, []);

// While checking: show splash (null state)
if (showOnboarding === null) return <SplashScreen />;
if (showOnboarding) return <OnboardingScreen onComplete={() => { markOnboardingComplete(); setShowOnboarding(false); }} />;
// Else: normal auth gate
```

**UI components needed:**
- `OnboardingDot` — small circle, filled vs outlined, animates on page change
- `OnboardingSlide` — accepts `icon`, `title`, `body`, `isLast`, `onNext`, `onSkip`
- Slide transitions: use `react-native-reanimated` FadeIn/SlideInRight (already in stack)
- Page indicator dots at bottom center

**SplashScreen (very simple):**
```tsx
// Full LinearGradient, centered TreePine icon + "DoorDrill" text
// Shown only while checking onboarding state (~100ms)
```

### Verification
- First install: onboarding slides shown → push permission prompt → LoginScreen
- Return visit (after login): onboarding never shown again
- Skip button on any slide: jumps to push permission step
- Push denied: app proceeds normally, no retry nag
- Reanimated transitions: no jank, no layout shift
- iOS/Android: push permission dialog appears correctly on each platform

---

## Phase OB4 — First-Drill Guided Experience

### Goal
A rep's first drill should feel guided, not cold. When a rep has zero completed sessions, the HomeScreen shows a "Start Your First Drill" CTA with a brief explanation. The scenario selection includes a "Recommended for Beginners" badge on the easiest scenario. During the first session, a minimal tips overlay appears at session start (dismissed after 3 seconds). After the first drill, the ScoreScreen adds a congratulatory message for the first completion. After this phase, churn from confusion on day one is eliminated.

### What to build

**Backend: mark scenarios with difficulty**

Add `difficulty` field to `Scenario` model if not present:
```python
difficulty: str = "medium"  # "easy" | "medium" | "hard"
```

Add migration: `ALTER TABLE scenarios ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'medium'`.

In scenario seed data, mark one scenario as `"easy"` (the "Friendly Homeowner" or equivalent).

**Backend: `GET /rep/scenarios` should include `difficulty` in response**

In `ScenarioBrief` schema, add `difficulty: str`.

**Mobile: `HomeScreen` — first-drill CTA**

Add hook to detect first-timer status:
```typescript
// Rep is a first-timer if history.length === 0 and no active sessions
const isFirstTimer = history.length === 0 && !hasActiveSessions;
```

Show a highlighted "banner card" above the normal content when `isFirstTimer`:
```tsx
{isFirstTimer && (
  <Pressable style={styles.firstDrillBanner} onPress={navigateToScenarioPicker}>
    <View style={styles.firstDrillIcon}>
      <Zap size={24} color={colors.accent} />
    </View>
    <View style={styles.firstDrillText}>
      <Text style={styles.firstDrillTitle}>Start Your First Drill</Text>
      <Text style={styles.firstDrillSubtitle}>Takes 3–5 minutes. Your AI homeowner is waiting.</Text>
    </View>
    <ChevronRight size={20} color={colors.accent} />
  </Pressable>
)}
```

**Mobile: `ScenarioPickerScreen` (or existing scenario list) — beginner badge**

On each scenario card, if `scenario.difficulty === "easy"`:
```tsx
<View style={styles.beginnerBadge}>
  <Zap size={10} color="#fff" />
  <Text style={styles.beginnerBadgeText}>Recommended for Beginners</Text>
</View>
```

Sort: easy scenarios first when rep has 0 history.

**Mobile: `PreSessionScreen` — first-session tips overlay**

Pass an `isFirstSession` prop from navigation params. When `isFirstSession === true`, show a brief tips card before the pulsing orb animation:

```tsx
{isFirstSession && !tipsDismissed && (
  <Animated.View entering={FadeIn} exiting={FadeOut} style={styles.tipsCard}>
    <Text style={styles.tipsTitle}>A few tips:</Text>
    {[
      "Speak naturally — just like a real door",
      "The AI will respond as a real homeowner would",
      "You'll get a score and breakdown after",
    ].map((tip, i) => (
      <Text key={i} style={styles.tipItem}>• {tip}</Text>
    ))}
  </Animated.View>
)}
```

Auto-dismiss after 4 seconds:
```typescript
useEffect(() => {
  if (isFirstSession) {
    const timer = setTimeout(() => setTipsDismissed(true), 4000);
    return () => clearTimeout(timer);
  }
}, [isFirstSession]);
```

**Mobile: `ScoreScreen` — first-drill congrats**

Pass `isFirstDrill` via navigation or detect via history length in ScoreScreen. Show above the score orb:

```tsx
{isFirstDrill && (
  <View style={styles.firstDrillCongrats}>
    <Text style={styles.congratsEmoji}>🎉</Text>
    <Text style={styles.congratsTitle}>First Drill Complete!</Text>
    <Text style={styles.congratsBody}>Nice work. Here's how you did.</Text>
  </View>
)}
```

### Verification
- Rep with 0 history: HomeScreen shows first-drill banner
- Rep with 1+ history: banner hidden
- Easy scenario appears first in picker for first-timers
- Tips overlay appears on first session, auto-dismisses after 4s
- Tips overlay NOT shown on subsequent sessions
- Congrats header shown on first ScoreScreen view only (not on history revisit)
- No hard-coded session counts — all derived from live API data

---

## Phase OB5 — Manager Onboarding (Dashboard Wizard)

### Goal
When a manager registers for DoorDrill for the first time, they see a simple 3-step setup wizard in the dashboard. This ensures the platform is correctly configured before inviting reps. After this phase, manager time-to-first-rep-invited is under 5 minutes, and no manager ships with a blank organization.

### What to build

**Backend: track manager onboarding state**

Add `onboarding_completed_at TIMESTAMPTZ NULL` to `users` table (migration).

Add `GET /manager/onboarding-status` endpoint:
```python
class OnboardingStatus(BaseModel):
    steps: list[OnboardingStep]
    is_complete: bool

class OnboardingStep(BaseModel):
    id: str  # "org_profile" | "first_scenario" | "first_invite"
    label: str
    is_complete: bool
    cta_url: str  # dashboard route to complete this step

@router.get("/onboarding-status", response_model=OnboardingStatus)
async def get_onboarding_status(manager: User = Depends(get_current_manager), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, manager.org_id)
    scenario_count = await db.scalar(select(func.count()).select_from(Scenario).where(Scenario.org_id == manager.org_id))
    invite_count = await db.scalar(select(func.count()).select_from(Invitation).where(Invitation.org_id == manager.org_id))

    steps = [
        OnboardingStep(
            id="org_profile",
            label="Set up your organization",
            is_complete=bool(org and org.industry and org.name),
            cta_url="/settings/organization",
        ),
        OnboardingStep(
            id="first_scenario",
            label="Create your first drill scenario",
            is_complete=scenario_count > 0,
            cta_url="/scenarios/new",
        ),
        OnboardingStep(
            id="first_invite",
            label="Invite your first rep",
            is_complete=invite_count > 0,
            cta_url="/reps/invite",
        ),
    ]
    is_complete = all(s.is_complete for s in steps)
    if is_complete and not manager.onboarding_completed_at:
        manager.onboarding_completed_at = datetime.utcnow()
        await db.commit()

    return OnboardingStatus(steps=steps, is_complete=is_complete)
```

**Dashboard: `OnboardingChecklist` component (new)**

Shown at the top of `AnalyticsPage` (or as a sidebar widget) when `is_complete === false`. Uses Framer Motion for entrance animation.

```tsx
// src/components/OnboardingChecklist.tsx
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Circle, ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useOnboardingStatus } from "../hooks/useOnboardingStatus";

export function OnboardingChecklist() {
  const { data, isLoading } = useOnboardingStatus();
  const navigate = useNavigate();

  if (isLoading || !data || data.is_complete) return null;

  const completedCount = data.steps.filter((s) => s.is_complete).length;
  const progress = completedCount / data.steps.length;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className="bg-white/40 backdrop-blur-2xl border border-white/30 rounded-2xl shadow-sm p-6 mb-6"
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold text-[#1a1a1a]">Get DoorDrill ready</h2>
            <p className="text-sm text-[#6b7280]">{completedCount} of {data.steps.length} steps complete</p>
          </div>
          {/* Progress bar */}
          <div className="w-32 h-2 bg-gray-100 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-[#2D5A3D] rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${progress * 100}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>

        <div className="space-y-3">
          {data.steps.map((step) => (
            <motion.button
              key={step.id}
              onClick={() => navigate(step.cta_url)}
              className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-white/60 transition-colors text-left"
              whileTap={{ scale: 0.98 }}
            >
              {step.is_complete ? (
                <CheckCircle2 className="text-[#2D5A3D] shrink-0" size={20} />
              ) : (
                <Circle className="text-gray-300 shrink-0" size={20} />
              )}
              <span className={`flex-1 text-sm font-medium ${step.is_complete ? "text-gray-400 line-through" : "text-[#1a1a1a]"}`}>
                {step.label}
              </span>
              {!step.is_complete && <ChevronRight size={16} className="text-gray-400" />}
            </motion.button>
          ))}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
```

**Dashboard: `useOnboardingStatus` hook**
```typescript
// src/hooks/useOnboardingStatus.ts
import { useQuery } from "@tanstack/react-query";
import { fetchOnboardingStatus } from "../lib/api";

export function useOnboardingStatus() {
  return useQuery({
    queryKey: ["onboarding-status"],
    queryFn: fetchOnboardingStatus,
    staleTime: 30_000,
  });
}
```

**Dashboard: wire `OnboardingChecklist` into `AnalyticsPage`**
```tsx
// In AnalyticsPage.tsx, at the top of the returned JSX before the command center grid:
<OnboardingChecklist />
```

**Dashboard: invite rep modal (new, wired to `/reps/invite`)**

Simple modal accessible from sidebar and onboarding checklist:
```tsx
// InviteRepModal.tsx
// Email input + optional team dropdown
// POST /manager/invitations → show success with shareable invite link
// Error: "already invited" or "already registered" handled gracefully
```

### Verification
- Fresh manager account: onboarding checklist visible on dashboard
- Each step completion: checkbox turns green + line-through in real time (refetch after action)
- All 3 steps complete: checklist disappears (AnimatePresence exit animation), `onboarding_completed_at` set in DB
- Returning manager with all steps done: checklist never shown
- Invite modal: email sent, invitation row created, success message with copy link
- TypeScript: no `any`; `OnboardingStatus` and `OnboardingStep` types in `lib/types.ts`

---

## Summary: What OB1–OB5 Delivers

| Phase | Deliverable |
|-------|-------------|
| OB1 | Real JWT auth in mobile — Bearer token, SecureStore, silent refresh, session restoration |
| OB2 | Manager invite flow — invitation table, email invite, deep link to pre-filled RegisterScreen |
| OB3 | 3-slide onboarding flow for new reps + push permission prompt at right moment |
| OB4 | First-drill guidance — first-timer HomeScreen banner, beginner scenario badge, tips overlay, congrats on ScoreScreen |
| OB5 | Manager onboarding checklist — 3-step setup wizard in dashboard, auto-hides when complete |

After OB5, the complete funnel from manager signup → rep drill is seamless, production-quality, and requires zero manual setup by Cale.
