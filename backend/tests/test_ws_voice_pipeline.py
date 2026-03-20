import asyncio

import pytest
from sqlalchemy import select

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


def _run_empty_turn_until_clarification_idle(ws, *, sequence: int) -> list[dict]:
    ws.send_json(
        {
            "type": "client.audio.chunk",
            "sequence": sequence,
            "payload": {
                "transcript_hint": "",
                "codec": "opus",
            },
        }
    )

    messages: list[dict] = []
    for _ in range(80):
        message = ws.receive_json()
        messages.append(message)
        if (
            message["type"] == "server.session.state"
            and message["payload"].get("state") == "ai_idle"
            and message["payload"].get("clarification") is True
        ):
            return messages
    raise AssertionError("clarification turn did not finish")


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


class _RecordingLlmClient(MockLlmClient):
    def __init__(self) -> None:
        self.calls = 0

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80):
        self.calls += 1
        raise AssertionError("LLM should not be called for empty or sub-threshold transcripts")
        yield rep_text


class _RecordingTtsClient(MockTtsClient):
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def stream_audio(self, text: str):
        self.texts.append(text)
        async for chunk in super().stream_audio(text):
            yield chunk


class _LatencyAwareSttClient(MockSttClient):
    def __init__(self, *, final_delay_s: float) -> None:
        self.final_delay_s = final_delay_s
        self._finalized = asyncio.Event()

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        on_partial = payload.get("on_partial")
        if callable(on_partial) and hint:
            on_partial(hint, False)
        await asyncio.wait_for(self._finalized.wait(), timeout=1)
        await asyncio.sleep(self.final_delay_s)
        return SttTranscript(text=hint, confidence=0.98 if hint else 0.0, is_final=bool(hint), source=self.provider_name)

    async def trigger_finalization(self) -> None:
        self._finalized.set()


class _LatencyAwareLlmClient(MockLlmClient):
    def __init__(self, *, first_token_delay_s: float, reply: str) -> None:
        self.first_token_delay_s = first_token_delay_s
        self.reply = reply

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80):
        del rep_text, stage, system_prompt, max_tokens
        await asyncio.sleep(self.first_token_delay_s)
        yield self.reply


class _LatencyAwareTtsClient(MockTtsClient):
    def __init__(self, *, first_chunk_delay_s: float) -> None:
        self.first_chunk_delay_s = first_chunk_delay_s

    async def stream_audio(self, text: str):
        await asyncio.sleep(self.first_chunk_delay_s)
        async for chunk in super().stream_audio(text):
            yield chunk


def test_is_transcript_valid_single_valid_word():
    for transcript in ("Yeah", "Yes", "Right", "No"):
        assert voice_ws._is_transcript_valid(transcript) is True


def test_is_transcript_valid_noise_words():
    for transcript in ("um", "uh", "mm"):
        assert voice_ws._is_transcript_valid(transcript) is False


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


def test_ws_phase_latency_breakdown_stays_within_deterministic_budgets(client, seed_org, monkeypatch):
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(
            stt=_LatencyAwareSttClient(final_delay_s=0.03),
            llm=_LatencyAwareLlmClient(
                first_token_delay_s=0.05,
                reply="Before I agree to anything, I need to know the monthly budget and what is included.",
            ),
            tts=_LatencyAwareTtsClient(first_chunk_delay_s=0.04),
        ),
    )
    monkeypatch.setattr(voice_ws, "VAD_FINALIZE_DEBOUNCE_MS", 1)

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"

        ws.send_json({"type": "client.vad.state", "sequence": 1, "payload": {"speaking": True}})
        ws.send_json(
            {
                "type": "client.audio.chunk",
                "sequence": 2,
                "payload": {
                    "transcript_hint": "Hi, I can lower your monthly service cost today.",
                    "codec": "opus",
                },
            }
        )
        ws.send_json({"type": "client.vad.state", "sequence": 3, "payload": {"speaking": False}})

        committed = None
        for _ in range(200):
            message = ws.receive_json()
            if message["type"] == "server.turn.committed":
                committed = message
                break

        assert committed is not None
        ws.send_json({"type": "client.session.end", "sequence": 4, "payload": {}})

    phase_latency = committed["payload"]["phase_latency_breakdown"]
    assert phase_latency["stt_ms"] is not None
    assert phase_latency["analysis_ms"] is not None
    assert phase_latency["llm_first_token_ms"] is not None
    assert phase_latency["tts_first_audio_ms"] is not None
    assert phase_latency["total_turn_ms"] is not None
    assert phase_latency["stt_ms"] <= 150
    assert phase_latency["analysis_ms"] <= 75
    assert phase_latency["llm_first_token_ms"] <= 180
    assert phase_latency["tts_first_audio_ms"] <= 150
    assert phase_latency["total_turn_ms"] <= 450


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


def test_ws_empty_transcript_emits_clarification_without_llm_call(client, seed_org, monkeypatch):
    llm = _RecordingLlmClient()
    tts = _RecordingTtsClient()
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=llm, tts=tts),
    )
    monkeypatch.setattr(voice_ws.random, "choice", lambda responses: "I didn't catch that.")

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
                    "transcript_hint": "",
                    "codec": "opus",
                },
            }
        )

        messages: list[dict] = []
        for _ in range(50):
            message = ws.receive_json()
            messages.append(message)
            if (
                message["type"] == "server.session.state"
                and message["payload"].get("state") == "ai_idle"
                and message["payload"].get("clarification") is True
            ):
                break

        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    assert llm.calls == 0
    assert any(message["type"] == "server.ai.text.delta" for message in messages)
    assert any(message["type"] == "server.ai.text.done" for message in messages)
    assert any(message["type"] == "server.ai.audio.chunk" for message in messages)
    assert not any(message["type"] == "server.turn.committed" for message in messages)
    assert any(message["payload"].get("clarification") is True for message in messages if "payload" in message)
    assert any(text.endswith("I didn't catch that.") for text in tts.texts)

    db = SessionLocal()
    try:
        turns = db.scalars(select(SessionTurn).where(SessionTurn.session_id == session_id)).all()
        assert turns == []
    finally:
        db.close()


def test_consecutive_clarification_uses_recovery_pool(client, seed_org, monkeypatch):
    llm = _RecordingLlmClient()
    tts = _RecordingTtsClient()
    monkeypatch.setattr(
        voice_ws,
        "providers",
        ProviderSuite(stt=MockSttClient(), llm=llm, tts=tts),
    )
    monkeypatch.setattr(voice_ws.random, "choice", lambda responses: responses[0])

    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "server.session.state"

        first_messages = _run_empty_turn_until_clarification_idle(ws, sequence=1)
        second_messages = _run_empty_turn_until_clarification_idle(ws, sequence=2)

        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    assert llm.calls == 0
    assert any(message["type"] == "server.ai.text.delta" for message in first_messages)
    assert any(message["type"] == "server.ai.text.delta" for message in second_messages)
    assert len(tts.texts) >= 2
    assert tts.texts[0].endswith(voice_ws.CLARIFICATION_RESPONSES[0])
    assert tts.texts[1].endswith(voice_ws.CLARIFICATION_RECOVERY_RESPONSES[0])
