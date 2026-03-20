# DoorDrill Backend

The backend is a FastAPI service that provides DoorDrill's REST APIs, realtime WebSocket session gateway, grading pipeline, and manager analytics workflows.

## Requirements

- Python 3.11+

## Local Setup

```bash
cd backend
python -m pip install -e .[dev]
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Default local development uses:

- `sqlite:///./doordrill.db`
- header-based auth unless configured otherwise
- mock STT, LLM, and TTS providers so local runs do not require external credentials

See [`.env.example`](./.env.example) for the minimum local configuration surface.

## Validation

Run the backend test suite:

```bash
cd backend
pytest
```

Run migration smoke when changing schema or alembic behavior:

```bash
cd backend
alembic upgrade head
```

## Load and SLO Harness

Seed deterministic IDs for local or staging harness runs:

```bash
cd backend
python scripts/seed_load_data.py --field manager_id
python scripts/seed_load_data.py --field rep_id
python scripts/seed_load_data.py --field scenario_id
```

Run the staged websocket SLO gate:

```bash
cd backend
python scripts/load_test_ws.py \
  --manager-id <manager_id> \
  --rep-id <rep_id> \
  --scenario-id <scenario_id> \
  --ramp 50,100,200 \
  --slo-p50-ms 900 \
  --slo-p95-ms 1400 \
  --barge-slo-ms 150 \
  --min-success-rate 0.99 \
  --verify-replay \
  --trigger-barge-in \
  --min-realism-score 7.0 \
  --min-transcript-confidence 0.85 \
  --max-forbidden-phrase-hits 0 \
  --report-json ./load-reports/ws-ramp.json
```

Additional harness details are documented in [`scripts/README.md`](./scripts/README.md).

## Operational Notes

- Redis buffering is enabled automatically when `REDIS_URL` is set.
- Post-session workflows can be routed through Celery with `USE_CELERY=true`.
- Object storage presigning supports S3-compatible endpoints when storage credentials are configured.
- Auth supports both header-based local development and JWT-based flows, including JWKS-backed validation.
- Structured logs include request and session correlation fields for HTTP and WebSocket traffic.

## Operations References

- Environment matrix: [`docs/ops/staging-prod-env-matrix.md`](./docs/ops/staging-prod-env-matrix.md)
- Incident runbook: [`docs/ops/incident-runbook.md`](./docs/ops/incident-runbook.md)
