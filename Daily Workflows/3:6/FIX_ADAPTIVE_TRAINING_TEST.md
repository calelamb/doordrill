# Fix: test_adaptive_training.py — SQLite Isolation

## Problem

`test_adaptive_training.py` seeds sessions and scorecards by calling `SessionLocal()`
directly from the test helper `_seed_adaptive_history()`.  The API endpoint
`GET /manager/reps/{rep_id}/adaptive-plan` then uses `get_db()` which opens its own
`SessionLocal()` connection.

With SQLite the two connections share the same file, so committed data **should** be
visible.  However, SQLAlchemy's session identity-map means that when `build_plan` calls
`select(DrillSession)`, it may load session rows whose **lazy-loaded `scorecard`
relationship** hasn't been populated yet.  Specifically, the `DrillSession.scorecard`
attribute uses a lazy `SELECT` triggered by attribute access.  If the session object was
already in SQLAlchemy's identity map from before the scorecard was committed, the
relationship may not re-query and returns `None`, causing `snapshots` to be empty.

The symptom: `body["recommended_scenarios"]` is empty even though sessions exist.

## Fix

In `backend/tests/test_adaptive_training.py`, change `_seed_adaptive_history` to
**expire all cached objects** in the shared `engine` identity map by calling
`db.expire_all()` before close, or — simpler — by avoiding direct `SessionLocal()` in
the test and instead using the same session as `conftest.seed_org`.

The cleanest fix is to call `expire_all()` at the end of `_seed_adaptive_history`:

```python
db.expire_all()
db.close()
```

This forces SQLAlchemy to re-query on next access, so when the API handler's session
lazy-loads `session.scorecard`, it hits the database and finds the committed scorecard.

## Steps

1. Open `backend/tests/test_adaptive_training.py`.
2. In `_seed_adaptive_history`, after the final `db.commit()` and before `db.close()`,
   add `db.expire_all()`.
3. Run `cd backend && python -m pytest tests/test_adaptive_training.py -x -q` and
   confirm all 3 tests pass.
4. Run `cd backend && python -m pytest tests/ -x -q` to confirm no regressions.
