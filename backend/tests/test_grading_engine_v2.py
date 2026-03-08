import time
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.grading import GradingRun
from app.models.scorecard import Scorecard


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


def _run_session(
    client,
    seed_org: dict[str, str],
    assignment_id: str,
    transcript_hint: str,
    *,
    scenario_id: str | None = None,
) -> str:
    session = client.post(
        "/rep/sessions",
        json={
            "assignment_id": assignment_id,
            "rep_id": seed_org["rep_id"],
            "scenario_id": scenario_id or seed_org["scenario_id"],
        },
    )
    assert session.status_code == 200
    session_id = session.json()["id"]

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {"transcript_hint": transcript_hint, "codec": "opus"},
            }
        )
        for _ in range(80):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


def _await_scorecard_and_run(session_id: str) -> tuple[Scorecard, GradingRun]:
    scorecard = None
    grading_run = None
    for _ in range(40):
        db = SessionLocal()
        try:
            scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
            grading_run = db.scalar(
                select(GradingRun)
                .where(GradingRun.session_id == session_id)
                .order_by(GradingRun.created_at.desc())
            )
        finally:
            db.close()
        if scorecard is not None and grading_run is not None:
            break
        time.sleep(0.03)

    assert scorecard is not None
    assert grading_run is not None
    return scorecard, grading_run
