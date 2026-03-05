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


def _run_session(client, seed_org: dict[str, str], assignment_id: str) -> str:
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
        for _ in range(30):
            msg = ws.receive_json()
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
    session_id = _run_session(client, seed_org, assignment["id"])

    replay_resp = client.get(f"/manager/sessions/{session_id}/replay")
    assert replay_resp.status_code == 200
    replay = replay_resp.json()
    assert replay["session_id"] == session_id
    assert replay["audio_artifacts"]
    assert replay["transcript_turns"]
    assert replay["stage_timeline"]
    assert replay["transport_metrics"]["audio_frame_count"] > 0
    assert replay["scorecard"] is not None

    feed_resp = client.get("/manager/feed", params={"manager_id": seed_org["manager_id"]})
    assert feed_resp.status_code == 200
    items = feed_resp.json()["items"]
    assert len(items) >= 1
    assert any(item["session_id"] == session_id and item["overall_score"] is not None for item in items)


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


def test_event_persistence_integrity(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    db = SessionLocal()
    events = db.scalars(select(SessionEvent).where(SessionEvent.session_id == session_id)).all()
    db.close()

    assert len(events) > 0
    event_ids = {event.event_id for event in events}
    assert len(event_ids) == len(events)
    assert any(event.event_type == "server.turn.committed" for event in events)
    assert any(event.event_type == "server.session.state" and event.payload.get("transition") for event in events)
