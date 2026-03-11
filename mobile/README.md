# DoorDrill Mobile

The mobile app is an Expo React Native client for the rep training workflow on iOS and Android.

## Requirements

- Node.js 20+
- npm 10+
- Xcode for iOS simulator runs
- Android Studio for Android emulator runs

## Local Setup

```bash
cd mobile
npm install
cp .env.example .env
npm run start
```

For native runs:

```bash
cd mobile
npm run ios
npm run android
```

## Runtime Configuration

The app reads Expo public environment variables or falls back to `app.json` extras:

- `EXPO_PUBLIC_API_BASE_URL`
- `EXPO_PUBLIC_WS_BASE_URL`
- `EXPO_PUBLIC_PROJECT_ID` for physical-device Expo push token registration

Default local values point at:

- `http://127.0.0.1:8000`
- `ws://127.0.0.1:8000`

## Validation

```bash
cd mobile
npm run typecheck
```

## Implemented Workflow

- rep sign-in bootstrap
- assignment list with status filters
- drill session creation
- live drill screen backed by `WS /ws/sessions/{id}`
- scorecard review with category bars, highlights, and weakness tags

## Session Notes

- The mobile client supports hold-to-talk microphone capture through Expo AV.
- VAD state, audio chunks, and interruption cues are sent over the session WebSocket contract.
- A transcript hint can be attached with mic audio as a fallback for local development and degraded STT conditions.
