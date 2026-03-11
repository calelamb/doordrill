# Documentation Index

This directory and the top-level design documents are the canonical documentation surfaces for DoorDrill.

## Canonical Repository Docs

- [`../README.md`](../README.md): repository entry point and local setup
- [`../architecture.md`](../architecture.md): system architecture and planned platform shape
- [`ARCHITECTURE_CONFORMANCE.md`](./ARCHITECTURE_CONFORMANCE.md): backend contract parity tracking
- [`../SECURITY.md`](../SECURITY.md): security reporting process
- [`../backend/README.md`](../backend/README.md): backend setup, validation, and operational references
- [`../dashboard/README.md`](../dashboard/README.md): dashboard setup and local development notes
- [`../mobile/README.md`](../mobile/README.md): mobile setup and runtime configuration

## Operational Docs

- [`../backend/docs/ops/staging-prod-env-matrix.md`](../backend/docs/ops/staging-prod-env-matrix.md)
- [`../backend/docs/ops/incident-runbook.md`](../backend/docs/ops/incident-runbook.md)
- [`../backend/scripts/README.md`](../backend/scripts/README.md)

## Working Design Notes

Several root-level documents such as `*_ENGINE.md`, `*_ANALYSIS.md`, `IMPLEMENTATION_SPEC.md`, and files under `Daily Workflows/` capture planning history, implementation notes, and execution artifacts.

Those files are useful for engineering context, but they are not the primary source of truth for current repository setup, local development instructions, or operational workflows. When the working notes and canonical docs disagree, prefer the canonical docs listed above and update them as part of the same change.
