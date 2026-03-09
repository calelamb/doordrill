import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.session import SessionEvent


def _create_assignment(client, seed_org: dict[str, str]) -> dict:
    response = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "retry_policy": {"max_attempts": 2},
        },
    )
    assert response.status_code == 200
    return response.json()


def _create_session(client, seed_org: dict[str, str], assignment_id: str) -> str:
    response = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": seed_org["scenario_id"],
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def _run_turn(ws, text: str, sequence: int) -> tuple[str, str]:
    ws.send_json(
        {
            "type": "client.audio.chunk",
            "sequence": sequence,
            "payload": {
                "transcript_hint": text,
                "codec": "opus",
            },
        }
    )

    for _ in range(120):
        message = ws.receive_json()
        if message["type"] != "server.turn.committed":
            continue

        payload = message["payload"]
        rep_turn_id = payload.get("rep_turn_id")
        ai_turn_id = payload.get("ai_turn_id")
        assert rep_turn_id
        assert ai_turn_id
        return str(rep_turn_id), str(ai_turn_id)

    raise AssertionError("turn was not committed")


def test_ws_reconnect_churn_preserves_ledger_integrity(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment["id"])

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws_primary:
        first_state = ws_primary.receive_json()
        assert first_state["type"] == "server.session.state"
        first_rep, first_ai = _run_turn(
            ws_primary,
            "First attempt pitch before network drop.",
            sequence=1,
        )

    time.sleep(0.05)

    with client.websocket_connect(f"/ws/session/{session_id}") as ws_alias:
        reconnect_state = ws_alias.receive_json()
        assert reconnect_state["type"] == "server.session.state"
        second_rep, second_ai = _run_turn(
            ws_alias,
            "Second attempt pitch after reconnect.",
            sequence=1,
        )
        ws_alias.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    replay = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/manager/sessions/{session_id}/replay")
        assert response.status_code == 200
        replay = response.json()
        if int(replay["transport_metrics"]["turn_count"]) >= 4:
            break
        time.sleep(0.1)

    assert replay is not None
    transcript_turn_ids = {turn["turn_id"] for turn in replay["transcript_turns"]}
    for turn_id in [first_rep, first_ai, second_rep, second_ai]:
        assert turn_id in transcript_turn_ids

    assert replay["transport_metrics"]["turn_count"] >= 4

    db = SessionLocal()
    try:
        events = db.scalars(select(SessionEvent).where(SessionEvent.session_id == session_id)).all()
    finally:
        db.close()

    assert len(events) > 0
    event_ids = [event.event_id for event in events]
    assert len(set(event_ids)) == len(event_ids)

    connected_states = [
        event
        for event in events
        if event.event_type == "server.session.state" and event.payload.get("state") == "connected"
    ]
    assert len(connected_states) >= 2

    committed_events = [event for event in events if event.event_type == "server.turn.committed"]
    assert len(committed_events) >= 2
