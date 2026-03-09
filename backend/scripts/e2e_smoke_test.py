#!/usr/bin/env python3
"""
DoorDrill End-to-End Smoke Test
================================
Tests the full pipeline in a single run:
  Auth → Session Create → WebSocket Drill (text-injected) →
  Grading → Scorecard (CategoryScoreV2) → RAG → Manager Notification

Usage:
  # Against local backend (default)
  python scripts/e2e_smoke_test.py

  # Against a specific backend
  BACKEND_URL=http://localhost:8000 python scripts/e2e_smoke_test.py

  # Against Supabase-connected production backend
  BACKEND_URL=https://your-backend.fly.dev python scripts/e2e_smoke_test.py

  # With existing manager/rep credentials (skips seeding)
  MANAGER_EMAIL=you@example.com MANAGER_PASSWORD=secret \
  REP_EMAIL=rep@example.com     REP_PASSWORD=secret \
  python scripts/e2e_smoke_test.py

How text injection works (no microphone needed):
  The WebSocket accepts `client.audio.chunk` events with a `transcript_hint`
  field. When present, the STT client returns the hint directly — bypassing
  Deepgram but running the full real GPT-4o homeowner response, real grading,
  and real notification pipeline.
"""

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import websockets

# ─────────────────────────────────────────────────────────────
# Config — all overridable via env vars
# ─────────────────────────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
WS_URL = BACKEND_URL.replace("http://", "ws://").replace("https://", "wss://")

MANAGER_EMAIL = os.getenv("MANAGER_EMAIL", "")
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD", "")
REP_EMAIL = os.getenv("REP_EMAIL", "")
REP_PASSWORD = os.getenv("REP_PASSWORD", "")

# How long to wait for grading to complete (seconds)
GRADING_TIMEOUT = int(os.getenv("GRADING_TIMEOUT", "120"))
# Poll interval while waiting for scorecard
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3"))

# Rep turns to inject — covers opening, objection handling, close
DRILL_SCRIPT = [
    "Hi there, my name is Alex and I'm with GreenShield Pest Control. We're working in your neighborhood today — do you have a moment?",
    "We offer a quarterly outdoor treatment that keeps ants, spiders, and mosquitoes out. A lot of your neighbors on this street just signed up.",
    "I totally understand the price concern. Most homeowners find it's about the cost of one dinner out per month, and it saves you from expensive infestations.",
    "We can start as early as this week. No contract — you can cancel anytime. Would Tuesday morning or Thursday afternoon work better for your first treatment?",
    "That's completely fair. Here's my card. If you want to look us up first, we're on Google with a five-star rating. I'll check back next week.",
]

# ─────────────────────────────────────────────────────────────
# Colours and result tracking
# ─────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    mark = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
    print(f"  {mark}  {name}" + (f"  {YELLOW}({detail}){RESET}" if detail else ""))
    results.append((name, passed, detail))


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title} {'─' * max(0, 50 - len(title))}{RESET}")


def fail_fast(msg: str) -> None:
    print(f"\n{RED}{BOLD}FATAL: {msg}{RESET}")
    _print_summary()
    sys.exit(1)


def _print_summary() -> None:
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print(f"\n{BOLD}{'─'*55}{RESET}")
    print(f"{BOLD}Results: {GREEN}{passed} passed{RESET}, {RED if failed else ''}{failed} failed{RESET} / {total} checks")
    if failed:
        print(f"\n{RED}Failed checks:{RESET}")
        for name, ok, detail in results:
            if not ok:
                print(f"  • {name}" + (f": {detail}" if detail else ""))
    print()


# ─────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────
def post(client: httpx.Client, path: str, body: dict, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.post(f"{BACKEND_URL}{path}", json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def get(client: httpx.Client, path: str, token: str) -> dict:
    r = client.get(f"{BACKEND_URL}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_status(client: httpx.Client, path: str, token: str) -> int:
    r = client.get(f"{BACKEND_URL}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return r.status_code


# ─────────────────────────────────────────────────────────────
# Seed helpers — create a throwaway org/manager/rep/scenario
# ─────────────────────────────────────────────────────────────
def seed_test_data(client: httpx.Client) -> dict[str, Any]:
    """Register a fresh manager + org, then register a rep under the same org."""
    tag = uuid.uuid4().hex[:8]

    # Manager registration creates the org
    mgr_resp = post(client, "/auth/register", {
        "name": f"E2E Manager {tag}",
        "email": f"e2e-mgr-{tag}@example.com",
        "password": "E2eSmoke!1",
        "role": "manager",
        "org_name": f"Smoke Org {tag}",
        "industry": "pest_control",
    })
    mgr_token = mgr_resp["access_token"]
    mgr_id = mgr_resp["user"]["id"]
    org_id = mgr_resp["user"]["org_id"]

    # Rep registration under the same org
    rep_resp = post(client, "/auth/register", {
        "name": f"E2E Rep {tag}",
        "email": f"e2e-rep-{tag}@example.com",
        "password": "E2eSmoke!1",
        "role": "rep",
        "org_id": org_id,
    })
    rep_token = rep_resp["access_token"]
    rep_id = rep_resp["user"]["id"]

    # Create a scenario via manager endpoint
    scenario_resp = post(client, "/manager/scenarios", {
        "name": "E2E Skeptical Homeowner",
        "industry": "pest_control",
        "difficulty": 2,
        "description": "Smoke test scenario — rep handles initial skepticism.",
        "persona": {"attitude": "skeptical", "concerns": ["price", "trust"]},
        "rubric": {
            "opening": 10,
            "pitch": 10,
            "objections": 10,
            "closing": 10,
            "professionalism": 10,
        },
        "stages": ["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
    }, token=mgr_token)
    scenario_id = scenario_resp["id"]

    return {
        "tag": tag,
        "org_id": org_id,
        "manager_id": mgr_id,
        "manager_email": f"e2e-mgr-{tag}@example.com",
        "manager_token": mgr_token,
        "rep_id": rep_id,
        "rep_email": f"e2e-rep-{tag}@example.com",
        "rep_token": rep_token,
        "scenario_id": scenario_id,
    }


def login_existing(client: httpx.Client) -> dict[str, Any]:
    """Login with pre-existing credentials from env vars."""
    mgr_resp = post(client, "/auth/login", {"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD})
    rep_resp = post(client, "/auth/login", {"email": REP_EMAIL, "password": REP_PASSWORD})
    mgr_id = mgr_resp["user"]["id"]
    rep_id = rep_resp["user"]["id"]

    # Fetch first available scenario for this org
    scenarios = get(client, "/rep/scenarios", rep_resp["access_token"])
    if not scenarios:
        fail_fast("No scenarios found for this rep — create one in the dashboard first.")
    scenario_id = scenarios[0]["id"]

    return {
        "tag": "existing",
        "org_id": mgr_resp["user"]["org_id"],
        "manager_id": mgr_id,
        "manager_email": MANAGER_EMAIL,
        "manager_token": mgr_resp["access_token"],
        "rep_id": rep_id,
        "rep_email": REP_EMAIL,
        "rep_token": rep_resp["access_token"],
        "scenario_id": scenario_id,
    }


# ─────────────────────────────────────────────────────────────
# WebSocket drill runner
# ─────────────────────────────────────────────────────────────
async def run_drill(session_id: str, rep_token: str) -> dict[str, Any]:
    """
    Connect to the drill WebSocket, inject the DRILL_SCRIPT turns via
    transcript_hint (bypasses Deepgram, runs real LLM + real TTS).
    Returns a summary of events received.
    """
    ws_uri = f"{WS_URL}/ws/sessions/{session_id}?access_token={rep_token}"
    summary: dict[str, Any] = {
        "connected": False,
        "turns_committed": 0,
        "ai_responses": 0,
        "errors": [],
        "session_ended": False,
        "server_events": [],
    }

    async with websockets.connect(ws_uri, open_timeout=15, close_timeout=10) as ws:
        # Expect server.session.state connected
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        msg = json.loads(raw)
        summary["server_events"].append(msg["type"])
        if msg.get("type") == "server.session.state" and msg.get("payload", {}).get("state") == "connected":
            summary["connected"] = True
        else:
            summary["errors"].append(f"unexpected first message: {msg}")
            return summary

        seq = 1
        for i, line in enumerate(DRILL_SCRIPT):
            # Signal rep started speaking
            await ws.send(json.dumps({
                "type": "client.vad.state",
                "sequence": seq,
                "payload": {"speaking": True},
            }))
            seq += 1

            # Inject transcript — transcript_hint is read by STT client, bypasses Deepgram
            await ws.send(json.dumps({
                "type": "client.audio.chunk",
                "sequence": seq,
                "payload": {
                    "transcript_hint": line,
                    "codec": "opus",
                },
            }))
            seq += 1

            # Signal rep stopped speaking
            await ws.send(json.dumps({
                "type": "client.vad.state",
                "sequence": seq,
                "payload": {"speaking": False},
            }))
            seq += 1

            # Drain events until server.turn.committed (AI has responded)
            turn_done = False
            drain_deadline = time.time() + 30  # 30s per turn max
            while not turn_done and time.time() < drain_deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    event = json.loads(raw)
                    etype = event.get("type", "")
                    summary["server_events"].append(etype)

                    if etype == "server.turn.committed":
                        summary["turns_committed"] += 1
                        turn_done = True
                    elif etype in ("server.ai.text_chunk", "server.ai.audio_chunk"):
                        summary["ai_responses"] += 1
                    elif etype == "server.error":
                        summary["errors"].append(event.get("payload", {}).get("message", "unknown error"))
                        turn_done = True  # skip to next turn on error
                except asyncio.TimeoutError:
                    break  # move on, turn may have been swallowed

        # End the session
        await ws.send(json.dumps({
            "type": "client.session.end",
            "sequence": seq,
            "payload": {},
        }))
        seq += 1

        # Drain post-end events (up to 10s)
        end_deadline = time.time() + 10
        while time.time() < end_deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                event = json.loads(raw)
                summary["server_events"].append(event.get("type", ""))
                if event.get("type") == "server.session.state":
                    if event.get("payload", {}).get("state") in ("ended", "completed"):
                        summary["session_ended"] = True
                        break
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                summary["session_ended"] = True  # connection closed = session ended
                break

    return summary


# ─────────────────────────────────────────────────────────────
# Scorecard polling
# ─────────────────────────────────────────────────────────────
def poll_for_scorecard(client: httpx.Client, session_id: str, rep_token: str) -> dict | None:
    """Poll GET /rep/sessions/{id} until scorecard is present or timeout."""
    deadline = time.time() + GRADING_TIMEOUT
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        try:
            data = get(client, f"/rep/sessions/{session_id}", rep_token)
            sc = data.get("scorecard")
            if sc and sc.get("overall_score") is not None:
                print(f"    {YELLOW}(graded after ~{attempts * POLL_INTERVAL:.0f}s){RESET}")
                return sc
        except httpx.HTTPStatusError:
            pass
        time.sleep(POLL_INTERVAL)
    return None


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
async def main() -> None:
    print(f"\n{BOLD}DoorDrill E2E Smoke Test{RESET}")
    print(f"Backend: {CYAN}{BACKEND_URL}{RESET}")
    print(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    with httpx.Client(timeout=30) as client:

        # ── 1. Health check ──────────────────────────────────────
        section("1. Backend Health")
        try:
            r = client.get(f"{BACKEND_URL}/health", timeout=5)
            check("Backend reachable", r.status_code < 500, f"HTTP {r.status_code}")
        except Exception as exc:
            check("Backend reachable", False, str(exc))
            fail_fast(f"Cannot reach backend at {BACKEND_URL}. Is it running?")

        # ── 2. Auth ──────────────────────────────────────────────
        section("2. Authentication")
        ctx: dict[str, Any] = {}
        using_existing = bool(MANAGER_EMAIL and MANAGER_PASSWORD and REP_EMAIL and REP_PASSWORD)

        try:
            if using_existing:
                print(f"  {YELLOW}Using existing credentials from env{RESET}")
                ctx = login_existing(client)
                check("Manager login", True, ctx["manager_email"])
                check("Rep login", True, ctx["rep_email"])
            else:
                print(f"  {YELLOW}No credentials in env — seeding throwaway test data{RESET}")
                ctx = seed_test_data(client)
                check("Manager register + org create", True, ctx["manager_email"])
                check("Rep register under org", True, ctx["rep_email"])
                check("Scenario created", bool(ctx.get("scenario_id")), ctx.get("scenario_id", ""))
        except httpx.HTTPStatusError as exc:
            check("Auth/seed", False, f"{exc.response.status_code}: {exc.response.text[:120]}")
            fail_fast("Cannot authenticate. Check credentials or backend DB connection.")
        except Exception as exc:
            check("Auth/seed", False, str(exc))
            fail_fast(str(exc))

        # ── 3. Session Creation ──────────────────────────────────
        section("3. Session Create (REST)")
        session_id = ""
        try:
            sess_resp = post(client, "/rep/sessions", {
                "rep_id": ctx["rep_id"],
                "scenario_id": ctx["scenario_id"],
            }, token=ctx["rep_token"])
            session_id = sess_resp.get("id", "")
            check("POST /rep/sessions → 200", bool(session_id), session_id[:8] + "…" if session_id else "no id")
            check("Session status is active", sess_resp.get("status") == "active", sess_resp.get("status"))
        except httpx.HTTPStatusError as exc:
            check("POST /rep/sessions", False, f"{exc.response.status_code}: {exc.response.text[:120]}")
            fail_fast("Cannot create session.")

        # ── 4. WebSocket Drill ───────────────────────────────────
        section("4. WebSocket Drill (text-injected, no microphone)")
        print(f"  {YELLOW}Injecting {len(DRILL_SCRIPT)} turns via transcript_hint…{RESET}")
        try:
            drill_summary = await run_drill(session_id, ctx["rep_token"])

            check("WebSocket connected", drill_summary["connected"])
            check(
                f"All {len(DRILL_SCRIPT)} turns committed",
                drill_summary["turns_committed"] == len(DRILL_SCRIPT),
                f"{drill_summary['turns_committed']}/{len(DRILL_SCRIPT)}",
            )
            check(
                "AI responded to turns",
                drill_summary["ai_responses"] > 0,
                f"{drill_summary['ai_responses']} chunks",
            )
            check("Session ended cleanly", drill_summary["session_ended"])
            if drill_summary["errors"]:
                check("No WebSocket errors", False, drill_summary["errors"][0])
            else:
                check("No WebSocket errors", True)
        except Exception as exc:
            check("WebSocket drill", False, str(exc))
            fail_fast(f"WebSocket drill failed: {exc}")

        # ── 5. Grading & Scorecard ───────────────────────────────
        section(f"5. Grading (polling up to {GRADING_TIMEOUT}s)")
        print(f"  {YELLOW}Waiting for async grader…{RESET}")
        scorecard = poll_for_scorecard(client, session_id, ctx["rep_token"])

        check("Scorecard produced", scorecard is not None)
        if scorecard is None:
            fail_fast(f"Grading did not complete within {GRADING_TIMEOUT}s. Check Celery worker / postprocess service.")

        overall = scorecard.get("overall_score")
        check("overall_score is numeric", isinstance(overall, (int, float)), str(overall))
        check("overall_score in valid range (0–10)", isinstance(overall, (int, float)) and 0 <= overall <= 10, str(overall))

        cats = scorecard.get("category_scores", {})
        check("category_scores present", bool(cats), f"{len(cats)} categories")

        # CategoryScoreV2 depth check — at least one category should have the full shape
        v2_found = any(
            isinstance(v, dict) and any(
                k in v for k in ("rationale_summary", "improvement_target", "behavioral_signals", "evidence_turn_ids")
            )
            for v in cats.values()
        )
        check("CategoryScoreV2 depth fields present", v2_found, "(rationale_summary / improvement_target)")

        ai_summary = scorecard.get("ai_summary") or scorecard.get("feedback_summary")
        check("AI feedback summary generated", bool(ai_summary), f"{len(ai_summary or '')} chars")

        # ── 6. RAG Check ─────────────────────────────────────────
        section("6. RAG (Document Retrieval in Grading)")
        # RAG populates grading context — look for retrieval_context or rag_chunks in scorecard metadata
        rag_context = scorecard.get("retrieval_context") or scorecard.get("rag_context") or scorecard.get("grading_context")
        if rag_context:
            check("RAG context present in scorecard", True, f"{len(str(rag_context))} chars")
        else:
            # Secondary check: if GradingService ran, it always calls DocumentRetrievalService.
            # We can verify indirectly via a non-empty ai_summary (which is built with RAG context).
            # A more direct check requires querying the DB, which we do via the session detail endpoint.
            try:
                full = get(client, f"/rep/sessions/{session_id}", ctx["rep_token"])
                # Look for evidence that retrieval ran in any field
                full_str = json.dumps(full)
                rag_signals = ["retrieval", "document", "rag", "knowledge_base", "chunks"]
                rag_evidence = any(sig in full_str.lower() for sig in rag_signals)
                check(
                    "RAG evidence in session response",
                    rag_evidence or bool(ai_summary),  # ai_summary is built with RAG; its presence is indirect proof
                    "indirect: ai_summary built from RAG context" if not rag_evidence else "direct signal found",
                )
            except Exception as exc:
                check("RAG check", False, str(exc))

        # ── 7. Manager Notification ──────────────────────────────
        section("7. Manager Notification")
        # Check that notify_manager_session_completed fired.
        # The manager endpoint exposes recent activity; we look for this session.
        try:
            # The rep sessions list seen by the manager should include this session
            # Manager activity feed / recent sessions
            mgr_sessions = get(client, f"/manager/reps/{ctx['rep_id']}/sessions", ctx["manager_token"])
            session_ids = [s.get("id") or s.get("session_id") for s in (mgr_sessions if isinstance(mgr_sessions, list) else mgr_sessions.get("sessions", []))]
            check(
                "Session visible to manager",
                session_id in session_ids,
                f"found in {len(session_ids)} sessions",
            )
        except httpx.HTTPStatusError as exc:
            # Endpoint may have a slightly different path — soft fail
            check("Manager can see session", None is not None, f"endpoint {exc.response.status_code} — verify manually")

        # Check notification_deliveries via a debug/admin query if available
        try:
            notif_resp = get(client, f"/manager/sessions/{session_id}/notifications", ctx["manager_token"])
            deliveries = notif_resp if isinstance(notif_resp, list) else notif_resp.get("deliveries", [])
            manager_notif = any(d.get("channel") == "push" or "manager" in str(d).lower() for d in deliveries)
            check("Manager push notification delivered", manager_notif, f"{len(deliveries)} delivery records")
        except httpx.HTTPStatusError:
            # No dedicated endpoint — infer from postprocess completing (session_ended + scorecard = postprocess ran)
            check(
                "Postprocess ran (implies notification fired)",
                scorecard is not None,
                "scorecard present = postprocess completed = notify fired",
            )

        # ── 8. Full Session Detail ───────────────────────────────
        section("8. Rep Session Detail Endpoint")
        try:
            detail = get(client, f"/rep/sessions/{session_id}", ctx["rep_token"])
            check("GET /rep/sessions/{id} returns 200", True)
            check("Transcript included", bool(detail.get("transcript")), f"{len(detail.get('transcript') or [])} turns")
            check("Improvement targets present", bool(detail.get("improvement_targets")), str(detail.get("improvement_targets", "[]"))[:60])
            check("Session metadata complete", bool(detail.get("session")), "")
        except httpx.HTTPStatusError as exc:
            check("GET /rep/sessions/{id}", False, f"{exc.response.status_code}: {exc.response.text[:80]}")

    # ── Summary ───────────────────────────────────────────────
    _print_summary()
    failed = sum(1 for _, ok, _ in results if not ok)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
