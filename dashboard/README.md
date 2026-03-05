# DoorDrill Manager Dashboard (React)

Vite + React manager console scaffold for:
- manager feed
- replay details
- score override
- follow-up assignment creation
- manager analytics
- rep progress snapshot
- manager action timeline

## Run

```bash
cd dashboard
npm install
npm run dev
```

By default the app calls backend at `http://127.0.0.1:8000`.

Optional env:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Current scope

- Designed as a fast integration shell against backend contracts.
- Uses manager header auth scaffold (`x-user-id`, `x-user-role=manager`).
- Enter a manager ID in the UI to load data.
