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
  --concurrency 50
```

Outputs success/error counts and first-audio latency stats (`avg`, `p50`, `p95`, `max`).

Notes:
- This harness uses currently configured providers (mock by default).
- It is intended for iterative local benchmarking before full infra load tests.
