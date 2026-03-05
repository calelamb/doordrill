## Test

```bash
cd backend
pytest
```

## Load / SLO Harness

Seed deterministic IDs for local/staging harness runs:

```bash
cd backend
python scripts/seed_load_data.py --field manager_id
python scripts/seed_load_data.py --field rep_id
python scripts/seed_load_data.py --field scenario_id
```

Run staged SLO gate:

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
  --report-json ./load-reports/ws-ramp.json
```

## Ops Docs

- Environment matrix: `docs/ops/staging-prod-env-matrix.md`
- Incident runbook: `docs/ops/incident-runbook.md`

## Notes

- Redis buffering is enabled automatically if `REDIS_URL` is provided.
- Post-session workflow can run via Celery (`USE_CELERY=true`) with Redis broker/backend.
- Storage URLs now support S3/R2 presigning when object storage credentials are configured; otherwise fallback URLs are returned for local dev.
- Provider adapters for Deepgram/OpenAI/ElevenLabs are wired with real API paths plus mock fallback behavior to keep local development deterministic.
- Grading uses OpenAI judge mode when API credentials are present, with normalized JSON output and deterministic fallback scoring.
- Whisper transcript cleanup hook is implemented and runs when `WHISPER_CLEANUP_ENABLED=true`.
- Structured JSON logs now include request/session trace fields (`trace_id`, `request_id`) for HTTP and websocket flows.
