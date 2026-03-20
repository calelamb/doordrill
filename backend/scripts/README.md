# Backend Scripts

## `load_test_ws.py`

Synthetic websocket load harness for DoorDrill realtime sessions.

Usage:

```bash
cd backend
python scripts/load_test_ws.py \
  --api-base http://127.0.0.1:8000 \
  --ws-base ws://127.0.0.1:8000 \
  --manager-id <manager_id> \
  --rep-id <rep_id> \
  --scenario-id <scenario_id> \
  --ramp 50,100,200 \
  --slo-p50-ms 900 \
  --slo-p95-ms 1400 \
  --barge-slo-ms 150 \
  --verify-replay \
  --trigger-barge-in \
  --min-realism-score 7.0 \
  --min-transcript-confidence 0.85 \
  --max-forbidden-phrase-hits 0 \
  --report-json ./load-reports/ws-ramp.json
```

Outputs:

- first-audio latency (`avg`, `p50`, `p95`, `p99`, `max`)
- barge-in acknowledgment p95 latency
- replay turn-link integrity counts
- replay realism score summary
- replay transcript confidence summary
- forbidden fallback-phrase hit count across AI transcript turns
- JSON stage report with `overall_pass`

Notes:

- Harness uses currently configured providers (mock by default).
- `--verify-replay` enforces turn linkage validation against replay transcript turn IDs.
- Quality thresholds require `--verify-replay`.

## `seed_load_data.py`

Seeds deterministic manager/rep/scenario records for load harness and CI.

Usage:

```bash
cd backend
python scripts/seed_load_data.py
python scripts/seed_load_data.py --field manager_id
python scripts/seed_load_data.py --field rep_id
python scripts/seed_load_data.py --field scenario_id
```
