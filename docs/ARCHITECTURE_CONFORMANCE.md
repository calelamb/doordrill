# Architecture Conformance Matrix

This document tracks backend conformance against `architecture.md` endpoint and service contracts.

## Endpoint Conformance

| Contract | Status | Notes |
|---|---|---|
| `POST /auth/register` | Implemented | Local auth registration + JWT token issuance. |
| `POST /auth/login` | Implemented | Email/password login + JWT token issuance. |
| `POST /auth/refresh` | Implemented | Refresh token exchange. |
| `GET /manager/team` | Implemented | Returns reps for manager team. |
| `POST /manager/assignments` | Implemented | Existing contract. |
| `GET /manager/assignments` | Implemented | Added list endpoint with status filter. |
| `GET /manager/sessions` | Implemented | Added manager session list endpoint. |
| `GET /manager/sessions/{id}` | Implemented | Added detail endpoint. |
| `GET /manager/sessions/{id}/audio` | Implemented | Added presigned audio endpoint. |
| `PATCH /manager/scorecards/{id}` | Implemented | Existing contract. |
| `GET /manager/reps/{id}/progress` | Implemented | Existing contract. |
| `GET /manager/analytics` | Implemented | Existing contract. |
| `GET /rep/assignments` | Implemented | Existing contract. |
| `POST /rep/sessions` | Implemented | Existing contract. |
| `GET /rep/sessions` | Implemented | Added rep history endpoint. |
| `GET /rep/sessions/{id}` | Implemented | Existing contract. |
| `GET /rep/progress` | Implemented | Added rep progress endpoint. |
| `GET /scenarios` | Implemented | Added scenario listing endpoint. |
| `POST /scenarios` | Implemented | Added manager scenario creation. |
| `GET /scenarios/{id}` | Implemented | Added scenario detail endpoint. |
| `PUT /scenarios/{id}` | Implemented | Added manager scenario update. |
| `WS /ws/session/{id}` | Implemented | Alias added; canonical route remains `/ws/sessions/{id}`. |

## Service Conformance

| Service Capability | Status | Notes |
|---|---|---|
| FastAPI REST gateway | Implemented | Existing. |
| FastAPI WebSocket voice gateway | Implemented | Existing + interruption tracing. |
| Redis buffering | Implemented | Existing (`RedisEventBuffer`). |
| Celery task queue scaffold | Implemented | Added worker app + post-session tasks. |
| Post-session grading async path | Implemented | Inline by default; Celery-queued when enabled. |
| Post-session transcript cleanup | Implemented | Hook + artifact write; Whisper path config-gated. |
| Manager notification pipeline | Partially implemented | Service hook + logging/email-flag mode; provider wiring pending. |
| S3/R2 artifact URLs | Implemented | Presigning + fallback mode. |
| External IdP JWT validation | Implemented baseline | `JWT_JWKS_URL` support. |

## Remaining High-Impact Gaps

1. Provider-backed notification delivery (email + mobile push) with retries.
2. Deployed Celery worker + broker operationalization in staging/prod.
3. Full Whisper transcript cleanup in envs where audio retrieval and provider credentials are configured.
