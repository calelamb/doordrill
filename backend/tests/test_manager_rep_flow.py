import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.session import SessionEvent


def _create_assignment(client, seed_org: dict[str, str]) -> dict:
    payload = {
        "scenario_id": seed_org["scenario_id"],
        "rep_id": seed_org["rep_id"],
        "assigned_by": seed_org["manager_id"],
        "min_score_target": 7.5,
        "retry_policy": {"max_attempts": 3, "cooldown_minutes": 30},
    }
    response = client.post("/manager/assignments", json=payload)
    assert response.status_code == 200
    return response.json()


def _run_session(client, seed_org: dict[str, str], assignment_id: str, *, trigger_barge_in: bool = False) -> str:
    session_resp = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()  # server.session.state connected
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {
                    "transcript_hint": "Hi, I'm with Acme Pest Control. We can lower your service price today.",
                    "codec": "opus",
                },
            }
        )

        saw_commit = False
        barge_in_sent = False
        for _ in range(80):
            msg = ws.receive_json()
            if trigger_barge_in and not barge_in_sent and msg["type"] == "server.ai.audio.chunk":
                ws.send_json({"type": "client.vad.state", "sequence": 2, "payload": {"speaking": True}})
                barge_in_sent = True
            if msg["type"] == "server.turn.committed":
                saw_commit = True
                break
        assert saw_commit
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


def test_assignment_visibility_for_rep(client, seed_org):
    assignment = _create_assignment(client, seed_org)

    list_resp = client.get("/rep/assignments", params={"rep_id": seed_org["rep_id"]})
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["id"] == assignment["id"]
    assert items[0]["retry_policy"]["max_attempts"] == 3


def test_ws_ledger_replay_and_feed(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"], trigger_barge_in=True)

    replay_resp = client.get(f"/manager/sessions/{session_id}/replay")
    assert replay_resp.status_code == 200
    replay = replay_resp.json()
    assert replay["session_id"] == session_id
    assert replay["audio_artifacts"]
    assert replay["transcript_turns"]
    assert replay["stage_timeline"]
    assert replay["rep"]["id"] == seed_org["rep_id"]
    assert replay["scenario"]["id"] == seed_org["scenario_id"]
    assert replay["transport_metrics"]["audio_frame_count"] > 0
    assert replay["scorecard"] is not None
    assert "weakness_tags" in replay["scorecard"]
    assert replay["transport_metrics"]["barge_in_count"] >= 1
    assert replay["interruption_timeline"]
    assert replay["micro_behavior_timeline"]
    assert replay["micro_behavior_timeline"][0]["tone"] is not None
    assert replay["conversational_realism"]["turn_count"] >= 1
    assert replay["conversational_realism"]["average_score"] >= 1.0

    feed_resp = client.get("/manager/feed", params={"manager_id": seed_org["manager_id"]})
    assert feed_resp.status_code == 200
    items = feed_resp.json()["items"]
    assert len(items) >= 1
    matching = next(item for item in items if item["session_id"] == session_id)
    assert matching["overall_score"] is not None
    assert matching["rep_name"] == "Ray Rep"
    assert matching["scenario_name"] == "Skeptical Homeowner"
    assert matching["started_at"] is not None
    assert "latest_reviewed_at" in matching

    filtered = client.get(
        "/manager/feed",
        params={"manager_id": seed_org["manager_id"], "rep_id": seed_org["rep_id"], "reviewed": False},
    )
    assert filtered.status_code == 200
    assert any(item["session_id"] == session_id for item in filtered.json()["items"])


def test_live_session_endpoints(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_resp = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment["id"],
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]
    manager_headers = {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {
                    "transcript_hint": "I'm with Acme Pest Control and can lower your rate with broader coverage today.",
                    "codec": "opus",
                },
            }
        )

        for _ in range(80):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                break

        live_resp = client.get(
            "/manager/sessions/live",
            params={"manager_id": seed_org["manager_id"]},
            headers=manager_headers,
        )
        assert live_resp.status_code == 200
        live_body = live_resp.json()
        live_card = next(item for item in live_body["live_sessions"] if item["session_id"] == session_id)
        assert live_card["rep_name"] == "Ray Rep"
        assert live_card["scenario_name"] == "Skeptical Homeowner"
        assert live_card["elapsed_seconds"] >= 0
        assert live_card["turn_count"] >= 1

        transcript_resp = client.get(
            f"/manager/sessions/{session_id}/live-transcript",
            params={"manager_id": seed_org["manager_id"]},
            headers=manager_headers,
        )
        assert transcript_resp.status_code == 200
        transcript_body = transcript_resp.json()
        assert transcript_body["status"] == "active"
        assert transcript_body["rep"]["id"] == seed_org["rep_id"]
        assert transcript_body["turns"]
        assert transcript_body["stage_timeline"]

        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        live_after = client.get(
            "/manager/sessions/live",
            params={"manager_id": seed_org["manager_id"]},
            headers=manager_headers,
        )
        assert live_after.status_code == 200
        if session_id not in {item["session_id"] for item in live_after.json()["live_sessions"]}:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("session remained in live sessions after ending")


def test_manager_override_audit(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    replay = client.get(f"/manager/sessions/{session_id}/replay").json()
    scorecard_id = replay["scorecard"]["id"]

    override = client.patch(
        f"/manager/scorecards/{scorecard_id}",
        json={
            "reviewer_id": seed_org["manager_id"],
            "reason_code": "manager_coaching",
            "override_score": 8.8,
            "notes": "Good objection handling, better close than model gave credit for.",
        },
    )
    assert override.status_code == 200
    body = override.json()
    assert body["override_score"] == 8.8

    feed = client.get("/manager/feed", params={"manager_id": seed_org["manager_id"]}).json()["items"]
    item = next(i for i in feed if i["session_id"] == session_id)
    assert item["manager_reviewed"] is True


def test_followup_assignment_from_scorecard(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])
    replay = client.get(f"/manager/sessions/{session_id}/replay").json()
    scorecard_id = replay["scorecard"]["id"]

    followup = client.post(
        f"/manager/scorecards/{scorecard_id}/followup-assignment",
        json={
            "scenario_id": seed_org["scenario_id"],
            "assigned_by": seed_org["manager_id"],
            "retry_policy": {"max_attempts": 2},
        },
    )
    assert followup.status_code == 200
    body = followup.json()
    assert body["assignment"]["rep_id"] == seed_org["rep_id"]
    assert body["assignment"]["retry_policy"]["source_scorecard_id"] == scorecard_id
    assert "weakness_tags" in body


def test_event_persistence_integrity(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    events = []
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        db = SessionLocal()
        events = db.scalars(select(SessionEvent).where(SessionEvent.session_id == session_id)).all()
        db.close()
        if any(event.event_type == "server.turn.committed" for event in events):
            break
        time.sleep(0.1)

    assert len(events) > 0
    event_ids = {event.event_id for event in events}
    assert len(event_ids) == len(events)
    assert any(event.event_type == "server.turn.committed" for event in events)
    assert any(event.event_type == "server.session.state" and event.payload.get("transition") for event in events)


def test_manager_analytics_and_rep_progress(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    _run_session(client, seed_org, assignment["id"])

    analytics = client.get(
        "/manager/analytics",
        params={"manager_id": seed_org["manager_id"]},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert analytics.status_code == 200
    analytics_body = analytics.json()
    assert analytics_body["assignment_count"] >= 1
    assert analytics_body["sessions_count"] >= 1
    assert analytics_body["active_rep_count"] >= 1
    assert "completion_rate_by_rep" in analytics_body
    assert "scenario_pass_rates" in analytics_body
    assert "score_distribution_histogram" in analytics_body

    progress = client.get(
        f"/manager/reps/{seed_org['rep_id']}/progress",
        params={"manager_id": seed_org["manager_id"]},
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert progress.status_code == 200
    progress_body = progress.json()
    assert progress_body["rep_id"] == seed_org["rep_id"]
    assert progress_body["session_count"] >= 1
    assert progress_body["rep_name"] == "Ray Rep"
    assert "current_period_category_averages" in progress_body
    assert "weak_area_tags" in progress_body
    assert progress_body["latest_sessions"][0]["scenario_name"] == "Skeptical Homeowner"
