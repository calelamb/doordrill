def _create_assignment(client, seed_org: dict[str, str]) -> dict:
    response = client.post(
        "/manager/assignments",
        json={
            "scenario_id": seed_org["scenario_id"],
            "rep_id": seed_org["rep_id"],
            "assigned_by": seed_org["manager_id"],
            "min_score_target": 7.5,
            "retry_policy": {"max_attempts": 2},
        },
    )
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
        ws.receive_json()
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 1,
                "payload": {
                    "transcript_hint": "I wanted to show how we handle ants and spiders without locking you in.",
                    "codec": "opus",
                },
            }
        )
        for _ in range(60):
            msg = ws.receive_json()
            if msg["type"] == "server.turn.committed":
                break
        ws.send_json({"type": "client.session.end", "sequence": 2, "payload": {}})

    return session_id


def test_coaching_notes_flow_into_replay_and_rep_feedback(client, seed_org):
    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(client, seed_org, assignment["id"])

    replay = client.get(f"/manager/sessions/{session_id}/replay").json()
    scorecard_id = replay["scorecard"]["id"]

    created = client.post(
        f"/manager/scorecards/{scorecard_id}/coaching-notes",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
        json={
            "note": "Slow down after the first objection and confirm understanding.",
            "visible_to_rep": True,
            "weakness_tags": ["pace", "objection_handling"],
        },
    )
    assert created.status_code == 200
    note = created.json()
    assert note["visible_to_rep"] is True

    notes = client.get(
        f"/manager/scorecards/{scorecard_id}/coaching-notes",
        headers={"x-user-id": seed_org["manager_id"], "x-user-role": "manager"},
    )
    assert notes.status_code == 200
    note_items = notes.json()
    assert len(note_items) == 1
    assert note_items[0]["note"].startswith("Slow down")

    replay_after = client.get(f"/manager/sessions/{session_id}/replay").json()
    assert replay_after["coaching_notes"]
    assert replay_after["latest_coaching_note"]["id"] == note["id"]

    rep_feedback = client.get(
        f"/rep/sessions/{session_id}",
        headers={"x-user-id": seed_org["rep_id"], "x-user-role": "rep"},
    )
    assert rep_feedback.status_code == 200
    assert rep_feedback.json()["manager_coaching_note"]["id"] == note["id"]
