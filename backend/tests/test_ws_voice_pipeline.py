import asyncio

from app.db.session import SessionLocal
from app.models.session import SessionTurn
from app.services.provider_clients import MockLlmClient, MockSttClient, MockTtsClient, ProviderSuite, SttTranscript
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


class _FinalizeAwareSttClient(MockSttClient):
    def __init__(self) -> None:
        self._finalized = asyncio.Event()
        self.trigger_calls = 0

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        on_partial = payload.get("on_partial")
        if callable(on_partial) and hint:
            on_partial(hint, False)
        await asyncio.wait_for(self._finalized.wait(), timeout=1)
        return SttTranscript(text=hint, confidence=0.98 if hint else 0.0, is_final=bool(hint), source=self.provider_name)

    async def trigger_finalization(self) -> None:
        self.trigger_calls += 1
        self._finalized.set()


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


def test_ws_vad_end_triggers_stt_finalization_and_logs_latency(client, seed_org, monkeypatch, caplog):
    stt = _FinalizeAwareSttClient()
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=stt, llm=MockLlmClient(), tts=MockTtsClient()),
    )
    monkeypatch.setattr(voice_ws, "VAD_FINALIZE_DEBOUNCE_MS", 1)

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with caplog.at_level("INFO"):
        with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
            connected = ws.receive_json()
            assert connected["type"] == "server.session.state"

            ws.send_json({"type": "client.vad.state", "sequence": 1, "payload": {"speaking": True}})
            ws.send_json(
                {
                    "type": "client.audio.chunk",
                    "sequence": 2,
                    "payload": {"transcript_hint": "Hi, I can lower your pest control bill today.", "codec": "opus"},
                }
            )
            ws.send_json({"type": "client.vad.state", "sequence": 3, "payload": {"speaking": False}})

            saw_commit = False
            for _ in range(200):
                message = ws.receive_json()
                if message["type"] == "server.turn.committed":
                    saw_commit = True
                    break

            assert saw_commit
            ws.send_json({"type": "client.session.end", "sequence": 4, "payload": {}})

    assert stt.trigger_calls == 1
    latency_records = [record for record in caplog.records if record.message == "turn_latency"]
    assert latency_records
    assert latency_records[0].turn_index >= 1
    assert latency_records[0].total_ms >= 0


def test_ws_session_state_includes_system_prompt_token_count(client, seed_org, monkeypatch):
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=MockLlmClient(), tts=MockTtsClient()),
    )

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"
        assert "system_prompt_token_count" in connected["payload"]

        turn_messages = _run_turn(ws, text="Hi, I'm with Acme Pest Control.", sequence=1)
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    state_payloads = [message["payload"] for message in turn_messages if message["type"] == "server.session.state"]
    assert any(payload.get("system_prompt_token_count", 0) > 0 for payload in state_payloads)


def test_ws_barge_in_emits_audio_interrupt(client, seed_org, monkeypatch):
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=MockLlmClient(), tts=MockTtsClient()),
    )

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"

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

        messages: list[dict] = []
        barge_in_sent = False
        for _ in range(200):
            message = ws.receive_json()
            messages.append(message)
            if message["type"] == "server.ai.audio.chunk" and not barge_in_sent:
                ws.send_json({"type": "client.vad.state", "sequence": 2, "payload": {"speaking": True}})
                barge_in_sent = True
            if message["type"] == "server.turn.committed":
                break

        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    assert barge_in_sent is True
    assert any(message["type"] == "server.audio.interrupt" for message in messages)


def test_ws_commits_transcript_audit_and_turn_analysis(client, seed_org, monkeypatch):
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=MockLlmClient(), tts=MockTtsClient()),
    )

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"
        messages = _run_turn(ws, text="Hi, I'm with Acme Pest Control and price matters.", sequence=1)
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    stt_final = next(message for message in messages if message["type"] == "server.stt.final")
    committed = next(message for message in messages if message["type"] == "server.turn.committed")

    assert stt_final["payload"]["transcript_normalization"]["raw_text"]
    assert stt_final["payload"]["transcript_normalization"]["normalized_text"]
    assert committed["payload"]["turn_analysis"]["stage_intent"]
    assert committed["payload"]["turn_analysis"]["reaction_intent"]
    assert committed["payload"]["response_plan"]["reaction_goal"]
    assert "phase_latency_breakdown" in committed["payload"]
    assert "transcript_quality" in committed["payload"]

    db = SessionLocal()
    try:
        rep_turn = db.get(SessionTurn, committed["payload"]["rep_turn_id"])
        assert rep_turn is not None
        assert rep_turn.raw_transcript_text == stt_final["payload"]["transcript_normalization"]["raw_text"]
        assert rep_turn.normalized_transcript_text == stt_final["payload"]["transcript_normalization"]["normalized_text"]
        assert rep_turn.transcript_provider == stt_final["payload"]["provider"]
        assert rep_turn.transcript_confidence == stt_final["payload"]["confidence"]
    finally:
        db.close()
