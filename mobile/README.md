# DoorDrill Mobile (iOS + Android)

Expo + React Native client focused on the rep workflow.

## Implemented v1 flow

- Rep sign-in bootstrap (`rep_id`)
- Assignment list (`GET /rep/assignments`)
- Start drill session (`POST /rep/sessions`)
- Live drill screen using websocket contract (`WS /ws/sessions/{id}`)
- Scorecard screen (`GET /rep/sessions/{id}`)

## Environment

Use either Expo public env vars or `app.json` extras:

- `EXPO_PUBLIC_API_BASE_URL`
- `EXPO_PUBLIC_WS_BASE_URL`

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

- Voice microphone capture is intentionally abstracted in `src/services/audio.ts` and staged for the next phase.
- Current live drill uses typed utterance events against the same websocket contract as desktop dashboard rep mode.
