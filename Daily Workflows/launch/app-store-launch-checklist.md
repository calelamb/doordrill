# DoorDrill — App Store Launch Checklist

> **Target stores:** Apple App Store (iOS) + Google Play Store (Android)
> Stack: Expo (React Native) · FastAPI backend · Fly.io · Supabase

---

## Phase 1 — Accounts & Legal (Week 1)

### Apple
- [ ] Enroll in **Apple Developer Program** — $99/yr at developer.apple.com/enroll
- [ ] Accept latest Apple Developer Agreement in App Store Connect
- [ ] Add engineering lead as Admin in App Store Connect (Users & Access)
- [ ] Create a new App record in App Store Connect (Bundle ID: e.g. `com.doordrill.app`)

### Google
- [ ] Create **Google Play Developer** account — $25 one-time at play.google.com/console
- [ ] Accept Distribution Agreement
- [ ] Create a new App in Play Console (set as App, not Game; Free)

### Legal / Privacy
- [ ] Write and host a **Privacy Policy** (required by both stores) — covers data collected: name, email, audio recordings, session scores
- [ ] Write and host **Terms of Service**
- [ ] Ensure privacy policy URL is reachable (not localhost)
- [ ] Add both URLs to App Store Connect and Play Console listings

---

## Phase 2 — Expo & Build Setup (Week 1–2)

### app.json / app.config.js
- [ ] Set `expo.name` → `"DoorDrill"`
- [ ] Set `expo.slug` → `"doordrill"`
- [ ] Set `expo.version` → `"1.0.0"`
- [ ] Set `expo.ios.bundleIdentifier` → `"com.doordrill.app"`
- [ ] Set `expo.android.package` → `"com.doordrill.app"`
- [ ] Set `expo.ios.buildNumber` → `"1"`
- [ ] Set `expo.android.versionCode` → `1`
- [ ] Add `expo.ios.infoPlist` entries for all permission usage descriptions:
  - `NSMicrophoneUsageDescription` — "DoorDrill uses your microphone to record sales practice sessions."
  - `NSCameraUsageDescription` (if applicable)
- [ ] Add `expo.android.permissions` array with `RECORD_AUDIO`
- [ ] Set `expo.plugins` includes `expo-notifications` config with correct push credentials
- [ ] Set `expo.scheme` → `"doordrill"` (for deep links)
- [ ] Confirm `expo.splash` and `expo.icon` point to real assets (1024×1024 PNG, no alpha for iOS)

### EAS Build
- [ ] Install EAS CLI: `npm install -g eas-cli`
- [ ] Run `eas login` and authenticate with Expo account
- [ ] Run `eas build:configure` — generates `eas.json`
- [ ] Configure `eas.json` with `production` profile for both platforms:
  ```json
  "production": {
    "ios": { "distribution": "store" },
    "android": { "buildType": "app-bundle" }
  }
  ```
- [ ] Run `eas credentials` — let EAS manage provisioning profile + signing certificate (iOS) and upload keystore (Android). **Store the keystore backup somewhere safe — losing it means you can never update the app.**

### Privacy Manifest (iOS — required since May 2024)
- [ ] Add `PrivacyInfo.xcprivacy` file declaring API usage (required if using `UserDefaults`, file timestamps, etc.)
- [ ] Declare `NSPrivacyAccessedAPITypes` if app or any SDK accesses protected APIs

---

## Phase 3 — Backend Production Readiness (Week 1–2)

*From the production checklist — these must be done before submission:*

- [ ] Batch 1–5 Codex prompts all merged and passing
- [ ] `alembic upgrade head` run against production Supabase DB
- [ ] All production env vars set on Fly.io (`fly secrets set ...`):
  - `DATABASE_URL` (pooler URL)
  - `REDIS_URL`
  - `JWT_SECRET` (rotated, 32+ char random)
  - `OPENAI_API_KEY`
  - `DEEPGRAM_API_KEY`
  - `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
  - `SENTRY_DSN`
  - `AUTH_REQUIRED=true`
  - `ENVIRONMENT=production`
- [ ] `fly deploy` completes successfully, `GET /health` returns `{"status":"ok"}`
- [ ] Production API URL set in `mobile/src/services/config.ts` (not LAN IP)
- [ ] `e2e_smoke_test.py` run against production URL — all passing
- [ ] Rate limiting confirmed active on `/auth/login` and `/auth/register`
- [ ] HTTPS enforced — no HTTP traffic accepted

---

## Phase 4 — Push Notifications Credentials (Week 2)

### iOS (APNs)
- [ ] In Apple Developer Portal → Certificates → create **APNs Key** (.p8 file)
- [ ] Note the Key ID and Team ID
- [ ] In Expo Dashboard (or `eas credentials`): upload APNs key
- [ ] Test push notification delivery on physical iOS device (simulator doesn't support push)

### Android (FCM)
- [ ] Create Firebase project at console.firebase.google.com
- [ ] Add Android app with package `com.doordrill.app`
- [ ] Download `google-services.json` → place in `mobile/android/app/`
- [ ] Copy FCM Server Key → add to Expo Dashboard push credentials
- [ ] Test push notification delivery on physical Android device

---

## Phase 5 — Store Assets (Week 2)

### App Icon
- [ ] 1024×1024 PNG, no transparency, no rounded corners (Apple adds them)
- [ ] Matches `expo.icon` in app.json

### Screenshots (required)
**iOS** — need at least 6.9" (iPhone 16 Pro Max) and 12.9" (iPad Pro) sizes:
- [ ] Minimum 3 screenshots per device size, maximum 10
- [ ] Suggested screens: Drill in progress, Score screen, Manager dashboard, Leaderboard, Onboarding
- [ ] Resolution: 1320×2868 (6.9"), 2048×2732 (iPad)
- [ ] No device frames required but recommended

**Android:**
- [ ] Minimum 2 screenshots, 16:9 or 9:16 ratio
- [ ] Same suggested screens as iOS

### App Preview Video (optional but recommended for iOS)
- [ ] 15–30 second MP4 showing a drill session end-to-end
- [ ] Must be captured on actual device or simulator at correct resolution

### Store Listing Copy
- [ ] **App name:** "DoorDrill" (30 char max on iOS)
- [ ] **Subtitle (iOS):** e.g. "D2D Sales Training Simulator" (30 char max)
- [ ] **Short description (Android):** 80 chars max
- [ ] **Full description:** 4000 chars max — write benefit-first, mention AI coaching, manager dashboard, real-time scoring
- [ ] **Keywords (iOS):** 100 chars max — "sales training, door to door, sales simulator, d2d, coaching, roleplay"
- [ ] **Support URL:** e.g. doordrill.com/support or a simple email link
- [ ] **Marketing URL** (optional)
- [ ] **Category:** Business (iOS) / Business (Android)
- [ ] **Age rating:** 4+ (iOS) — fill out the content questionnaire, nothing violent/adult
- [ ] **Pricing:** Free (or set subscription if monetizing at launch)

---

## Phase 6 — Final QA Before Submission (Week 3)

### Device Testing
- [ ] Test on physical iPhone (not just simulator) — audio recording, WebSocket, push
- [ ] Test on physical Android device
- [ ] Test on at least one older device (iPhone 12 / Android with API 29+)
- [ ] Test airplane mode behavior — graceful error states, not crash
- [ ] Test deep link `doordrill://reset-password?token=...` on both platforms
- [ ] Test app backgrounding mid-drill — does it recover or show an error?
- [ ] Test onboarding flow from a fresh install (delete app, reinstall)

### Auth & Security
- [ ] Confirm `calejlamb@gmail.com` and at least 2 test rep accounts work end-to-end in production
- [ ] Confirm password reset flow works with real email delivery
- [ ] Confirm JWT refresh works — let token expire, verify auto-refresh
- [ ] Confirm logout clears SecureStore tokens

### Functional
- [ ] Complete a full drill: login → start session → speak 3+ turns → view score
- [ ] Manager can view rep's completed session and score
- [ ] Push notification received when score is ready
- [ ] Invite flow: manager sends invite → rep registers → rep appears in dashboard

---

## Phase 7 — Submission (Week 3)

### iOS
- [ ] Run `eas build --platform ios --profile production` — produces `.ipa`
- [ ] Upload build: `eas submit --platform ios` (or upload manually via Transporter app)
- [ ] In App Store Connect: select the build, fill all metadata, answer export compliance questions (likely "No encryption" unless you added custom crypto)
- [ ] Submit for review
- [ ] Monitor review status — typical turnaround 24–72 hrs
- [ ] Respond promptly to any rejection with the specific fix Apple requests

### Android
- [ ] Run `eas build --platform android --profile production` — produces `.aab`
- [ ] In Play Console: create new release in **Internal Testing** track first
- [ ] Upload `.aab`, fill release notes
- [ ] Promote to **Closed Testing** (beta) → gather 10+ opt-in testers
- [ ] After 14 days of closed testing with no crashes, promote to **Production**
  > ⚠️ Google requires a closed testing period before opening to all users for new accounts

---

## Phase 8 — Post-Launch (Week 4+)

- [ ] Set up **Crashlytics or Sentry alerts** for new error spikes
- [ ] Monitor Fly.io metrics — CPU, memory, response time after first real users
- [ ] Set up App Store Connect **analytics** — impressions, downloads, retention
- [ ] Monitor Supabase connection pool usage — upgrade plan if needed
- [ ] Respond to first App Store reviews within 48 hours
- [ ] Tag the Git commit: `git tag v1.0.0 && git push --tags`
- [ ] Announce to beta users

---

## Owner Assignment Template

| Area | Owner |
|------|-------|
| Apple Developer account | |
| Google Play account | |
| Privacy policy / ToS hosting | |
| EAS credentials & keystore backup | |
| Backend prod deploy (Fly.io) | |
| Push notification certificates | |
| Store screenshots & copy | |
| Final QA device testing | |
| Submission & review monitoring | |
