from app.services.provider_clients import MockLlmClient, MockSttClient, MockTtsClient, ProviderSuite
from app.voice import ws as voice_ws


def _create_assignment(client, seed_org: dict[str, str]) -> str:
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
    return response.json()["id"]


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


def _run_turn(ws, *, text: str, sequence: int) -> list[dict]:
    ws.send_json(
        {
            "type": "client.vad.state",
            "sequence": sequence * 10,
            "payload": {"speaking": True},
        }
    )
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

    messages: list[dict] = []
    for _ in range(200):
        message = ws.receive_json()
        messages.append(message)
        if message["type"] == "server.turn.committed":
            return messages
    raise AssertionError("turn was not committed")


def test_ws_voice_pipeline_streams_events_in_order(client, seed_org, monkeypatch):
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=MockLlmClient(), tts=MockTtsClient()),
    )

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    all_messages: list[dict] = []
    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        all_messages.append(connected)
        assert connected["type"] == "server.session.state"
        assert connected["payload"]["state"] == "connected"

        ws.send_json({"type": "client.unsupported", "sequence": 0, "payload": {}})
        error = ws.receive_json()
        all_messages.append(error)
        assert error["type"] == "server.error"
        assert error["payload"]["code"] == "bad_event"

        turn_batches = [
            _run_turn(ws, text="Hi, I'm with Acme Pest Control.", sequence=1),
            _run_turn(ws, text="We can handle spiders and ants for less hassle.", sequence=2),
            _run_turn(ws, text="If it makes sense, we can get you scheduled today.", sequence=3),
        ]
        for batch in turn_batches:
            all_messages.extend(batch)

        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    assert [message["type"] for message in all_messages[:2]] == ["server.session.state", "server.error"]

    for batch in turn_batches:
        types = [message["type"] for message in batch]
        assert "server.session.state" in types
        assert "server.stt.partial" in types
        assert "server.stt.final" in types
        assert "server.ai.text.delta" in types
        assert "server.ai.audio.chunk" in types
        assert "server.turn.committed" in types

        partial_idx = types.index("server.stt.partial")
        final_idx = types.index("server.stt.final")
        text_idx = types.index("server.ai.text.delta")
        audio_idx = types.index("server.ai.audio.chunk")
        commit_idx = types.index("server.turn.committed")

        assert partial_idx < final_idx < text_idx < audio_idx < commit_idx

        text_positions = [idx for idx, value in enumerate(types) if value == "server.ai.text.delta"]
        if len(text_positions) >= 2:
            assert audio_idx < text_positions[1]

        first_text = next(message for message in batch if message["type"] == "server.ai.text.delta")
        first_audio = next(message for message in batch if message["type"] == "server.ai.audio.chunk")
        committed_turn = next(message for message in batch if message["type"] == "server.turn.committed")

        assert "micro_behavior" in first_text["payload"]
        assert "tone" in first_text["payload"]["micro_behavior"]
        assert "micro_behavior" in first_audio["payload"]
        assert "pause_before_ms" in first_audio["payload"]["micro_behavior"]
        assert committed_turn["payload"]["micro_behavior"]["realism_score"] >= 1.0

    committed = [message for message in all_messages if message["type"] == "server.turn.committed"]
    assert len(committed) == 3
