from __future__ import annotations

import base64
import json
import zlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.assignment import Assignment
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.training import ConversationQualitySignal
from app.models.types import AssignmentStatus, SessionStatus, TurnSpeaker
from app.services.provider_clients import MockLlmClient, MockSttClient, MockTtsClient, ProviderSuite
from app.services.document_retrieval_service import DocumentRetrievalService
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


def _run_turn(ws, *, text: str, sequence: int) -> None:
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

    for _ in range(200):
        message = ws.receive_json()
        if message["type"] == "server.turn.committed":
            return
    raise AssertionError("turn was not committed")


def _decompress_prompt(text: str) -> str:
    return zlib.decompress(base64.b64decode(text.encode("ascii"))).decode("utf-8")


def _manager_headers(seed_org: dict[str, str]) -> dict[str, str]:
    return {"x-user-id": seed_org["manager_id"], "x-user-role": "manager"}


def _seed_conversation_export_session(
    seed_org: dict[str, str],
    *,
    realism_score: float,
    with_quality_signal: bool,
    transcript_confidence: float = 0.97,
) -> dict[str, str]:
    db = SessionLocal()
    started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    try:
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "conversation_export_test"},
        )
        db.add(assignment)
        db.flush()

        session = DrillSession(
            assignment_id=assignment.id,
            rep_id=seed_org["rep_id"],
            scenario_id=seed_org["scenario_id"],
            prompt_version="conversation_v1",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=5),
            duration_seconds=300,
            status=SessionStatus.GRADED,
        )
        db.add(session)
        db.flush()

        rep_turn = SessionTurn(
            session_id=session.id,
            turn_index=1,
            speaker=TurnSpeaker.REP,
            stage="objection_handling",
            text="We can get you started today.",
            raw_transcript_text="We can get you started today.",
            normalized_transcript_text="We can get you started today.",
            transcript_provider="mock_stt",
            transcript_confidence=transcript_confidence,
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=10),
            objection_tags=["price"],
        )
        ai_turn = SessionTurn(
            session_id=session.id,
            turn_index=2,
            speaker=TurnSpeaker.AI,
            stage="objection_handling",
            text="I need more details before deciding.",
            system_prompt_snapshot=voice_ws._compress_prompt(
                "LAYER 1 - IMMERSION CONTRACT\nLAYER 3C - BEHAVIORAL DIRECTIVES\n"
            ),
            started_at=started_at + timedelta(seconds=10),
            ended_at=started_at + timedelta(seconds=20),
            objection_tags=[],
            emotion_before="skeptical",
            emotion_after="skeptical",
            mb_tone="guarded",
            mb_behaviors=["tone_shift", "objection_aware"],
            mb_realism_score=realism_score,
            was_graded=True,
            is_high_quality=realism_score >= 8.0,
        )
        db.add_all([rep_turn, ai_turn])

        db.add(
            Scorecard(
                session_id=session.id,
                overall_score=7.2,
                category_scores={},
                highlights=[],
                ai_summary="conversation export seed",
                evidence_turn_ids=[],
                weakness_tags=[],
            )
        )

        if with_quality_signal:
            db.add(
                ConversationQualitySignal(
                    session_id=session.id,
                    manager_id=seed_org["manager_id"],
                    org_id=seed_org["org_id"],
                    realism_rating=4,
                    difficulty_appropriate=True,
                    signal_responsiveness=5,
                    notes="Solid but slightly soft.",
                    flagged_turn_ids=[],
                )
            )

        db.commit()
        return {"session_id": session.id, "ai_turn_id": ai_turn.id}
    finally:
        db.close()


def test_compress_prompt_round_trips_losslessly():
    prompt = (
        "LAYER 1 - IMMERSION CONTRACT\n"
        "You are a real homeowner in a live door-to-door roleplay.\n"
        "Never break character.\n"
    )

    compressed = voice_ws._compress_prompt(prompt)

    assert _decompress_prompt(compressed) == prompt


def test_ws_persists_system_prompt_snapshot_for_ai_turns_only(client, seed_org, monkeypatch):
    assert ConversationQualitySignal.__tablename__ == "conversation_quality_signals"
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
        assert connected["payload"]["state"] == "connected"

        _run_turn(ws, text="Hi, I'm with Acme Pest Control.", sequence=1)
        ws.send_json({"type": "client.session.end", "sequence": 99, "payload": {}})

    db = SessionLocal()
    try:
        turns = db.scalars(
            select(SessionTurn)
            .where(SessionTurn.session_id == session_id)
            .order_by(SessionTurn.turn_index.asc())
        ).all()
    finally:
        db.close()

    assert turns
    rep_turns = [turn for turn in turns if turn.speaker == TurnSpeaker.REP]
    ai_turns = [turn for turn in turns if turn.speaker == TurnSpeaker.AI]

    assert rep_turns
    assert ai_turns
    assert all(turn.system_prompt_snapshot is None for turn in rep_turns)
    assert all(turn.system_prompt_snapshot is not None for turn in ai_turns)
    assert all("LAYER 1 - IMMERSION CONTRACT" in _decompress_prompt(turn.system_prompt_snapshot or "") for turn in ai_turns)


def test_conversation_quality_signal_post_and_get_upserts(client, seed_org):
    assignment_id = _create_assignment(client, seed_org)
    session_id = _create_session(client, seed_org, assignment_id)

    create_response = client.post(
        f"/manager/sessions/{session_id}/conversation-quality",
        headers=_manager_headers(seed_org),
        json={
            "realism_rating": 3,
            "difficulty_appropriate": True,
            "signal_responsiveness": 4,
            "notes": "Homeowner softened too quickly.",
            "flagged_turn_ids": ["turn-1"],
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["session_id"] == session_id
    assert created["realism_rating"] == 3
    assert created["flagged_turn_ids"] == ["turn-1"]

    update_response = client.post(
        f"/manager/sessions/{session_id}/conversation-quality",
        headers=_manager_headers(seed_org),
        json={
            "realism_rating": 5,
            "difficulty_appropriate": False,
            "signal_responsiveness": 2,
            "notes": "Too reactive to closing pressure.",
            "flagged_turn_ids": ["turn-2", "turn-3"],
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["id"] == created["id"]
    assert updated["realism_rating"] == 5
    assert updated["difficulty_appropriate"] is False
    assert updated["signal_responsiveness"] == 2
    assert updated["flagged_turn_ids"] == ["turn-2", "turn-3"]

    get_response = client.get(
        f"/manager/sessions/{session_id}/conversation-quality",
        headers=_manager_headers(seed_org),
    )
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["id"] == created["id"]
    assert fetched["notes"] == "Too reactive to closing pressure."

    db = SessionLocal()
    try:
        count = db.scalar(
            select(ConversationQualitySignal)
            .where(ConversationQualitySignal.session_id == session_id)
        )
        assert count is not None
        rows = db.scalars(
            select(ConversationQualitySignal).where(ConversationQualitySignal.session_id == session_id)
        ).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_conversation_export_returns_valid_jsonl_and_marks_signal_exported(client, seed_org):
    seeded = _seed_conversation_export_session(seed_org, realism_score=8.4, with_quality_signal=True)

    response = client.get(
        "/admin/training-signals/conversation-export",
        params={"format": "jsonl"},
        headers=_manager_headers(seed_org),
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.strip()]
    assert lines

    record = json.loads(lines[0])
    assert record["session_id"] == seeded["session_id"]
    assert record["turn_id"] == seeded["ai_turn_id"]
    assert "input" in record
    assert "output" in record
    assert "signals" in record
    assert "metadata" in record
    assert "system_prompt" in record["input"]
    assert "LAYER 1 - IMMERSION CONTRACT" in record["input"]["system_prompt"]
    assert record["input"]["conversation_history"][0]["speaker"] == "rep"
    assert record["output"]["text"] == "I need more details before deciding."
    assert record["signals"]["mb_realism_score"] == 8.4
    assert record["signals"]["manager_realism_rating"] == 4
    assert record["signals"]["manager_flagged"] is False
    assert record["metadata"]["prompt_version"] == "conversation_v1"

    db = SessionLocal()
    try:
        signal = db.scalar(
            select(ConversationQualitySignal).where(ConversationQualitySignal.session_id == seeded["session_id"])
        )
        assert signal is not None
        assert signal.exported_at is not None
        assert signal.export_batch_id
    finally:
        db.close()


def test_conversation_export_quality_signal_only_excludes_sessions_without_signal(client, seed_org):
    with_signal = _seed_conversation_export_session(seed_org, realism_score=8.1, with_quality_signal=True)
    _seed_conversation_export_session(seed_org, realism_score=8.1, with_quality_signal=False)

    response = client.get(
        "/admin/training-signals/conversation-export",
        params={"format": "jsonl", "quality_signal_only": "true"},
        headers=_manager_headers(seed_org),
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.strip()]
    session_ids = {json.loads(line)["session_id"] for line in lines}
    assert session_ids == {with_signal["session_id"]}


def test_conversation_export_high_value_bucket_filters_for_clean_high_confidence_examples(client, seed_org):
    good = _seed_conversation_export_session(seed_org, realism_score=8.8, with_quality_signal=True)
    _seed_conversation_export_session(
        seed_org,
        realism_score=6.2,
        with_quality_signal=False,
        transcript_confidence=0.62,
    )

    response = client.get(
        "/admin/training-signals/conversation-export",
        params={
            "format": "jsonl",
            "bucket": "high_value",
            "min_transcript_confidence": 0.9,
            "min_eval_score": 7.5,
        },
        headers=_manager_headers(seed_org),
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.strip()]
    assert lines
    records = [json.loads(line) for line in lines]
    assert {record["session_id"] for record in records} == {good["session_id"]}
    assert records[0]["signals"]["transcript_confidence"] >= 0.9
    assert records[0]["signals"]["session_eval_overall_score"] >= 7.5
    assert records[0]["metadata"]["export_bucket"] == "high_value"


def test_retrieve_for_topic_falls_back_gracefully_when_pgvector_unavailable(seed_org, monkeypatch):
    db = SessionLocal()
    try:
        assignment = Assignment(
            scenario_id=seed_org["scenario_id"],
            rep_id=seed_org["rep_id"],
            assigned_by=seed_org["manager_id"],
            status=AssignmentStatus.COMPLETED,
            retry_policy={"source": "retrieval-fallback-test"},
        )
        db.add(assignment)
        db.flush()

        from app.models.knowledge import OrgDocument, OrgDocumentChunk
        from app.models.types import OrgDocumentFileType, OrgDocumentStatus

        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Fallback Notes",
            original_filename="fallback.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/fallback.txt",
            status=OrgDocumentStatus.READY,
            chunk_count=1,
            token_count=20,
            uploaded_by=seed_org["manager_id"],
        )
        db.add(document)
        db.flush()
        db.add(
            OrgDocumentChunk(
                document_id=document.id,
                org_id=seed_org["org_id"],
                chunk_index=0,
                text="Monthly plan pricing and service coverage details for homeowners.",
                token_count=10,
                embedding=[0.1, 0.2, 0.3],
            )
        )
        db.commit()

        async def fail_embed(self, text: str):
            raise RuntimeError("embedding unavailable")

        monkeypatch.setattr(DocumentRetrievalService, "_embed_query", fail_embed)
        monkeypatch.setattr(DocumentRetrievalService, "_supports_postgres_vector_search", lambda self, db: False)

        service = DocumentRetrievalService()
        chunks = service.retrieve_for_topic(
            db,
            org_id=seed_org["org_id"],
            topic="monthly plan pricing coverage",
            context_hint="",
            k=3,
            min_score=0.70,
        )

        assert chunks
        assert chunks[0].document_name == "Fallback Notes"
        assert "pricing" in chunks[0].text.lower()
        assert chunks[0].similarity_score >= 0.70
    finally:
        db.close()
