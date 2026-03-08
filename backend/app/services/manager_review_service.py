from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.types import ReviewReason, UserRole
from app.models.user import User
from app.services.warehouse_etl_service import WarehouseEtlService


class ManagerReviewService:
    def __init__(self) -> None:
        self.warehouse_etl_service = WarehouseEtlService()

    def _session_bundle(
        self,
        db: Session,
        *,
        session_id: str,
    ) -> tuple[DrillSession | None, Assignment | None, Scorecard | None]:
        row = db.execute(
            select(DrillSession, Assignment, Scorecard)
            .outerjoin(Assignment, Assignment.id == DrillSession.assignment_id)
            .outerjoin(Scorecard, Scorecard.session_id == DrillSession.id)
            .where(DrillSession.id == session_id)
        ).first()
        if row is None:
            return None, None, None
        session, assignment, scorecard = row
        return session, assignment, scorecard

    def _scorecard_bundle(
        self,
        db: Session,
        *,
        scorecard_id: str,
    ) -> tuple[Scorecard | None, DrillSession | None, Assignment | None]:
        row = db.execute(
            select(Scorecard, DrillSession, Assignment)
            .join(DrillSession, DrillSession.id == Scorecard.session_id)
            .join(Assignment, Assignment.id == DrillSession.assignment_id)
            .where(Scorecard.id == scorecard_id)
        ).first()
        if row is None:
            return None, None, None
        scorecard, session, assignment = row
        return scorecard, session, assignment

    def _manager_owns_assignment(self, reviewer: User, assignment: Assignment | None) -> bool:
        if assignment is None:
            return False
        if reviewer.role == UserRole.ADMIN:
            return True
        return assignment.assigned_by == reviewer.id

    def bulk_mark_reviewed(
        self,
        db: Session,
        *,
        reviewer: User,
        session_ids: list[str],
        idempotency_key: str,
        notes: str | None = None,
    ) -> dict:
        created_count = 0
        items: list[dict] = []

        for session_id in session_ids:
            session, assignment, scorecard = self._session_bundle(db, session_id=session_id)
            if session is None:
                items.append({"session_id": session_id, "status": "not_found"})
                continue
            if not self._manager_owns_assignment(reviewer, assignment):
                items.append({"session_id": session_id, "status": "forbidden"})
                continue
            if scorecard is None:
                items.append({"session_id": session_id, "status": "not_graded"})
                continue

            existing_review = db.scalar(
                select(ManagerReview)
                .where(ManagerReview.scorecard_id == scorecard.id)
                .order_by(ManagerReview.reviewed_at.desc())
            )
            if existing_review is not None:
                items.append(
                    {
                        "session_id": session_id,
                        "scorecard_id": scorecard.id,
                        "status": "already_reviewed",
                        "review_id": existing_review.id,
                    }
                )
                continue

            review = ManagerReview(
                scorecard_id=scorecard.id,
                reviewer_id=reviewer.id,
                reviewed_at=datetime.now(timezone.utc),
                reason_code=ReviewReason.REVIEW_ONLY,
                override_score=None,
                notes=notes,
                idempotency_key=idempotency_key,
            )
            db.add(review)
            db.flush()
            created_count += 1
            items.append(
                {
                    "session_id": session_id,
                    "scorecard_id": scorecard.id,
                    "status": "created",
                    "review_id": review.id,
                }
            )

        skipped_count = len(items) - created_count
        return {
            "requested_count": len(session_ids),
            "created_count": created_count,
            "skipped_count": skipped_count,
            "items": items,
        }

    def create_coaching_note(
        self,
        db: Session,
        *,
        scorecard_id: str,
        reviewer: User,
        note: str,
        visible_to_rep: bool,
        weakness_tags: list[str] | None = None,
    ) -> ManagerCoachingNote | None:
        scorecard, source_session, assignment = self._scorecard_bundle(db, scorecard_id=scorecard_id)
        if scorecard is None or not self._manager_owns_assignment(reviewer, assignment):
            return None

        row = ManagerCoachingNote(
            scorecard_id=scorecard.id,
            reviewer_id=reviewer.id,
            note=note,
            visible_to_rep=visible_to_rep,
            weakness_tags=list(weakness_tags or []),
        )
        db.add(row)
        db.flush()
        if source_session is not None:
            self.warehouse_etl_service.write_session(db, source_session.id, commit=False)
        return row

    def list_coaching_notes(self, db: Session, *, scorecard_id: str) -> list[ManagerCoachingNote]:
        return db.scalars(
            select(ManagerCoachingNote)
            .where(ManagerCoachingNote.scorecard_id == scorecard_id)
            .order_by(ManagerCoachingNote.created_at.desc())
        ).all()

    def latest_rep_visible_note(self, db: Session, *, session_id: str) -> ManagerCoachingNote | None:
        return db.scalar(
            select(ManagerCoachingNote)
            .join(Scorecard, Scorecard.id == ManagerCoachingNote.scorecard_id)
            .where(
                Scorecard.session_id == session_id,
                ManagerCoachingNote.visible_to_rep.is_(True),
            )
            .order_by(ManagerCoachingNote.created_at.desc())
        )
