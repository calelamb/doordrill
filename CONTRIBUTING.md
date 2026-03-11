# Contributing to DoorDrill

This repository is maintained as an active engineering codebase. Treat changes as production-bound work, even when the target surface is still pre-production.

## Branching

- Branch from `main`.
- Keep feature branches current with `main` before requesting review or merging.
- Prefer short-lived branches with one focused change set.

## Development Expectations

- Update documentation when API contracts, setup steps, operational behavior, or developer workflows change.
- Do not commit secrets, local `.env` files, database files, or generated artifacts.
- Keep changes scoped. Separate refactors from behavior changes unless they are tightly coupled.

## Validation

Run the checks that match the surface area you changed:

### Backend

```bash
cd backend
pytest
```

If you changed migrations, auth, realtime behavior, or performance-sensitive code, also run the relevant smoke or harness commands documented in [`backend/README.md`](./backend/README.md) and [`backend/scripts/README.md`](./backend/scripts/README.md).

### Dashboard

```bash
cd dashboard
npm install
npm run build
```

### Mobile

```bash
cd mobile
npm install
npm run typecheck
```

## Pull Requests

Every pull request should include:

- a concise description of what changed and why
- the local validation that was run
- screenshots or recordings for UI changes when applicable
- rollout or risk notes for behavior changes that affect contracts, auth, or realtime flows

If a change affects multiple surfaces, call that out explicitly so review can cover the integration points.
