from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge import OrgDocument, OrgDocumentChunk
from app.models.types import OrgDocumentFileType, OrgDocumentStatus
from app.models.user import User
from app.schemas.knowledge import RetrievedChunk
from app.services.manager_ai_coaching_service import ManagerAiCoachingService
from tests.test_manager_ai_coaching import _create_scored_session


def test_coaching_uses_company_material(seed_org, monkeypatch):
    _create_scored_session(
        seed_org,
        day_offset=2,
        overall_score=5.8,
        weakness_tags=["closing", "objection_handling"],
        ai_summary="Handled the opener well but failed to press the close after the first objection.",
    )
    _create_scored_session(
        seed_org,
        day_offset=4,
        overall_score=6.1,
        weakness_tags=["closing"],
        ai_summary="Good rapport, but the homeowner regained control when the rep softened the next-step ask.",
    )

    db = SessionLocal()
    try:
        rep = db.scalar(select(User).where(User.id == seed_org["rep_id"]))
        assert rep is not None

        document = OrgDocument(
            org_id=seed_org["org_id"],
            name="Closing Playbook",
            original_filename="closing.txt",
            file_type=OrgDocumentFileType.TXT,
            storage_key="org-documents/closing-playbook.txt",
            status=OrgDocumentStatus.READY,
            chunk_count=1,
            token_count=24,
            uploaded_by=seed_org["manager_id"],
        )
        db.add(document)
        db.flush()
        chunk = OrgDocumentChunk(
            document_id=document.id,
            org_id=seed_org["org_id"],
            chunk_index=0,
            text="Our company close requires isolating the objection, restating value, and asking directly for the next step.",
            token_count=18,
            embedding=[0.8, 0.6, 0.0],
        )
        db.add(chunk)
        db.commit()

        service = ManagerAiCoachingService()

        def fake_retrieve_for_topic(self, db, *, org_id: str, topic: str, context_hint: str = "", k: int = 5, min_score: float = 0.70):
            assert org_id == seed_org["org_id"]
            assert "coaching" in topic
            assert "closing" in topic
            return [
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    document_name=document.name,
                    text=chunk.text,
                    similarity_score=0.92,
                )
            ]

        def fake_claude(*, system_prompt: str, user_prompt: str, max_tokens: int, model: str | None = None):
            assert "Company training material relevant to this rep's weak areas:" in user_prompt
            assert "Closing Playbook" in user_prompt
            assert "asking directly for the next step" in user_prompt
            return {
                "headline": "Closing frame slips after resistance",
                "primary_weakness": "Closing",
                "root_cause": "The rep loses conviction after the first slowdown. That prevents a direct next-step ask.",
                "drill_recommendation": 'Assign "Skeptical Homeowner" difficulty 3',
                "coaching_script": "Hold the frame after resistance. Restate the value and ask directly for the next step. Use the company close every time.",
                "expected_improvement": "+0.8 on closing within 4 sessions",
            }

        monkeypatch.setattr(service.document_retrieval_service, "retrieve_for_topic", fake_retrieve_for_topic.__get__(service.document_retrieval_service))
        monkeypatch.setattr(service, "_call_claude_json", fake_claude)

        response = service.generate_rep_insight(db, rep=rep, period_days=30)
    finally:
        db.close()

    assert response.rep_id == seed_org["rep_id"]
    assert response.primary_weakness == "Closing"
