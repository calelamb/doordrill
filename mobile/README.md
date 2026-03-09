# DoorDrill Mobile (iOS + Android)

Expo + React Native client focused on the rep workflow.

## Implemented v1 flow

- Rep sign-in bootstrap (`rep_id`)
- Assignment list (`GET /rep/assignments`) with status filters
- Start drill session (`POST /rep/sessions`)
- Live drill screen using websocket contract (`WS /ws/sessions/{id}`)
  - hold-to-talk microphone capture (Expo AV)
  - VAD state signaling (`client.vad.state`)
  - audio payload send (`client.audio.chunk` with `audio_base64`)
  - interruption cue + reconnect controls
- Scorecard screen (`GET /rep/sessions/{id}`) with category bars/highlights/weakness tags

## Environment

Use either Expo public env vars or `app.json` extras:

- `EXPO_PUBLIC_API_BASE_URL`
- `EXPO_PUBLIC_WS_BASE_URL`
- `EXPO_PUBLIC_PROJECT_ID` (required on a physical device to fetch an Expo push token)

Defaults are set for local backend:

- `http://127.0.0.1:8000`
- `ws://127.0.0.1:8000`

## Run

```bash
cd mobile
npm install
npm run start
```

For native runs:

```bash
npm run ios
npm run android
```

## Notes

- The rep can provide an optional transcript hint while sending real mic audio; backend STT uses the hint only as fallback.
- AI audio playback is best-effort chunk playback in v1 and can be replaced with a dedicated streaming player in a later pass.
