# DoorDrill Backend Incident Runbook

This runbook covers the v1 highest-risk failure modes: worker outages, provider outages, and replay integrity drift.

## 1) Celery Worker Outage

### Symptoms

- `sessions.status` remains `processing` for long periods.
- `postprocess_runs.status` stuck in `pending` or `running`.
- Manager feed misses scorecards/notifications.

### Immediate Checks

1. Verify worker process health and queue depth.
2. Query backlog:

```sql
select task_type, status, count(*)
from postprocess_runs
group by task_type, status
order by task_type, status;
```

3. Inspect oldest pending run:

```sql
select session_id, task_type, status, attempts, next_retry_at, last_error
from postprocess_runs
where status in ('pending','retry')
order by created_at asc
limit 20;
```

### Mitigation

1. Restart worker deployment.
2. Confirm queue routing for:
   - `post_session.cleanup`
   - `post_session.grade`
   - `post_session.notify`
3. Requeue any stale `retry` rows by setting `next_retry_at = now()` if needed.
4. Verify new sessions progress to `completed` with scorecards.

## 2) Provider Outage (Deepgram/OpenAI/ElevenLabs/SendGrid/Expo)

### Symptoms

- Spike in provider timeout errors in logs.
- First-audio latency and retry counts increase.
- Notification deliveries move to `retry`/`failed`.

### Immediate Checks

1. Confirm provider status pages.
2. Sample failures:

```sql
select channel, status, retries, last_error, created_at
from notification_deliveries
where status in ('retry','failed')
order by created_at desc
limit 50;
```

3. Check postprocess task errors:

```sql
select task_type, status, attempts, last_error
from postprocess_runs
where status in ('retry','failed')
order by updated_at desc
limit 50;
```

### Mitigation

1. Keep API online and switch to fallback-friendly settings where possible.
2. For notification channel outage, temporarily disable affected channel:
   - `MANAGER_NOTIFICATION_EMAIL_ENABLED=false` and/or
   - `MANAGER_NOTIFICATION_PUSH_ENABLED=false`
3. For voice provider instability, reduce timeout pressure:
   - increase `PROVIDER_TIMEOUT_SECONDS` cautiously
   - validate mock fallback behavior in non-prod first
4. Re-enable channels/providers after recovery and monitor retry drain.

## 3) Replay Integrity Drift

### Symptoms

- Manager replay missing transcript/audio linkage.
- `turn_count` is zero despite completed sessions.
- Evidence turn IDs cannot be resolved.

### Immediate Checks

1. Spot check replay endpoint:
   - `GET /manager/sessions/{id}/replay`
2. Integrity SQL checks:

```sql
-- Duplicate event IDs must be zero per session
select session_id, event_id, count(*)
from session_events
group by session_id, event_id
having count(*) > 1;

-- Turn existence for completed sessions
select s.id as session_id, count(t.id) as turn_count
from sessions s
left join session_turns t on t.session_id = s.id
where s.status in ('processing','completed')
group by s.id
order by s.created_at desc
limit 100;
```

### Mitigation

1. Confirm Redis buffer availability and flush timing (`WS_FLUSH_INTERVAL_MS`).
2. Restart API pods if websocket workers are wedged.
3. Run SLO harness with `--verify-replay --trigger-barge-in` to validate full path.
4. If corruption is isolated, re-run postprocess for impacted session IDs and regenerate artifacts.

## 4) Recovery Validation Checklist

1. New sessions complete with:
   - transcript turns persisted
   - scorecard generated
   - notification delivery attempted/sent
2. SLO gate sample passes p50/p95 first-audio and barge-in p95 latency.
3. `postprocess_runs` backlog is draining and failure rate trends down.
4. Manager replay for canary org shows synchronized transcript/audio timeline.
