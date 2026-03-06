# MERGE TODO — Conversation Orchestrator

## Context

DoorDrill was developed across two separate directories that diverged.
The voice simulation work (emotion engine, micro-behaviors, adaptive training)
was built in a separate repo. All other backend work (management analytics,
notifications, Celery tasks) was built in this repo.

All unique files from the voice branch have already been copied over:
- `app/services/micro_behavior_engine.py` ✅ copied
- `app/services/adaptive_training_service.py` ✅ copied
- `app/schemas/adaptive_training.py` ✅ copied
- `backend/tests/test_adaptive_training.py` ✅ copied
- `backend/tests/test_conversation_orchestrator.py` ✅ copied
- `backend/tests/test_micro_behavior_engine.py` ✅ copied

## One file still needs manual merging

`app/services/conversation_orchestrator.py` was modified in both repos.

- **This repo's version** (265 lines): the base orchestrator, no emotion logic
- **Voice branch version** (362 lines): saved as `conversation_orchestrator_EMOTION_BRANCH.py`

## What Codex needs to do

1. Read both files:
   - `app/services/conversation_orchestrator.py` (current)
   - `app/services/conversation_orchestrator_EMOTION_BRANCH.py` (voice branch)

2. Identify what was added in the emotion branch that doesn't exist in current:
   - Emotional state machine initialization from scenario/persona data
   - Resistance scale tracking per session
   - Rep behavior signal evaluation
   - Emotion-aware system prompt construction
   - Unresolved objections seeding

3. Integrate those additions into the current file WITHOUT removing anything
   that exists in the current version. The current version may have imports,
   dependencies, or patterns that connect to the broader analytics/management
   layer — preserve all of it.

4. Once merged, delete `conversation_orchestrator_EMOTION_BRANCH.py`.

5. Run pytest to confirm nothing broke:
   ```
   cd backend && python -m pytest tests/ -x -q
   ```

## DO NOT touch these files — they are far more advanced in this repo
- `app/voice/ws.py` (724 lines here vs 449 in voice branch)
- `app/services/provider_clients.py` (538 lines here vs 192 in voice branch)
