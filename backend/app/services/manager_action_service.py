from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.analytics import AnalyticsFactAlert, AnalyticsFactManagerCalibration
from app.models.grading import GradingRun
from app.models.manager_action import ManagerActionLog
from app.models.scorecard import ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.training import OverrideLabel
from app.models.types import ReviewReason
from app.models.user import User
from app.services.warehouse_etl_service import WarehouseEtlService

DISAGREEMENT_THRESHOLD = 2.0
ALERT_PERIODS = ("7", "30", "90")


class ManagerActionService:
    def __init__(self) -> None:
        self.warehouse_etl_service = WarehouseEtlService()

    def log(
        self,
        db: Session,
        *,
        manager_id: str,
        action_type: str,
        target_type: str,
        target_id: str,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
        commit: bool = False,
    ) -> ManagerActionLog:
        log = ManagerActionLog(
            manager_id=manager_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            summary=summary,
            payload=payload or {},
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(log)
        if commit:
            db.commit()
            db.refresh(log)
        return log

    def submit_review(
        self,
        db: Session,
        *,
        reviewer: User,
        scorecard: Scorecard,
        source_session: DrillSession,
        reason_code: ReviewReason,
        override_score: float | None = None,
        notes: str | None = None,
    ) -> ManagerReview:
        review = ManagerReview(
            scorecard_id=scorecard.id,
            reviewer_id=reviewer.id,
            reviewed_at=datetime.now(timezone.utc),
            reason_code=reason_code,
            override_score=override_score,
            notes=notes,
        )
        db.add(review)
        db.flush()

        self.log(
            db,
            manager_id=reviewer.id,
            action_type="scorecard.reviewed",
            target_type="scorecard",
            target_id=scorecard.id,
            summary="Manager reviewed or overrode scorecard",
            payload={
                "reason_code": reason_code.value,
                "override_score": override_score,
                "has_notes": bool(notes),
            },
        )

        ai_score = scorecard.overall_score
        calibration = db.get(AnalyticsFactManagerCalibration, review.id)
        if calibration is None:
            calibration = AnalyticsFactManagerCalibration(
                review_id=review.id,
                manager_id=reviewer.id,
                reviewer_id=reviewer.id,
                scorecard_id=scorecard.id,
                session_id=source_session.id,
                reviewed_at=review.reviewed_at,
                ai_score=ai_score,
                override_score=override_score,
                delta_score=round((override_score - ai_score), 2) if override_score is not None and ai_score is not None else None,
                reason_code=reason_code.value,
            )
            db.add(calibration)
        else:
            calibration.manager_id = reviewer.id
            calibration.reviewer_id = reviewer.id
            calibration.scorecard_id = scorecard.id
            calibration.session_id = source_session.id
            calibration.reviewed_at = review.reviewed_at
            calibration.ai_score = ai_score
            calibration.override_score = override_score
            calibration.delta_score = round((override_score - ai_score), 2) if override_score is not None and ai_score is not None else None
            calibration.reason_code = reason_code.value

        if override_score is not None and ai_score is not None:
            delta = round(abs(override_score - ai_score), 2)
            grading_run = db.scalar(
                select(GradingRun)
                .where(GradingRun.session_id == source_session.id)
                .order_by(GradingRun.completed_at.desc(), GradingRun.created_at.desc())
            )
            if delta >= DISAGREEMENT_THRESHOLD:
                self._emit_disagreement_alert(
                    db,
                    review=review,
                    reviewer=reviewer,
                    scorecard=scorecard,
                    source_session=source_session,
                    grading_run=grading_run,
                    delta=delta,
                )
            self._write_override_label(
                db,
                review=review,
                reviewer=reviewer,
                scorecard=scorecard,
                source_session=source_session,
                grading_run=grading_run,
                delta=delta,
            )

        self.warehouse_etl_service.write_session(db, source_session.id, commit=False)
        return review

    def _write_override_label(
        self,
        db: Session,
        *,
        review: ManagerReview,
        reviewer: User,
        scorecard: Scorecard,
        source_session: DrillSession,
        grading_run: GradingRun | None,
        delta: float,
    ) -> None:
        if grading_run is None:
            grading_run = db.scalar(
                select(GradingRun)
                .where(GradingRun.session_id == source_session.id)
                .order_by(GradingRun.completed_at.desc(), GradingRun.created_at.desc())
            )
        if grading_run is None:
            return

        manager_review_count = int(
            db.scalar(select(func.count()).select_from(ManagerReview).where(ManagerReview.reviewer_id == reviewer.id)) or 0
        )
        if manager_review_count < 3 or delta < 1.0:
            label_quality = "low"
        elif delta >= 2.0 and manager_review_count >= 10:
            label_quality = "high"
        else:
            label_quality = "medium"

        label = db.scalar(select(OverrideLabel).where(OverrideLabel.review_id == review.id))
        if label is None:
            label = OverrideLabel(
                review_id=review.id,
                grading_run_id=grading_run.id,
                session_id=source_session.id,
                manager_id=reviewer.id,
                org_id=reviewer.org_id,
                ai_overall_score=float(scorecard.overall_score),
                ai_category_scores=dict(scorecard.category_scores or {}),
                override_overall_score=review.override_score,
                override_category_scores=None,
                override_reason_text=review.notes,
                override_delta_overall=delta,
                is_high_disagreement=delta >= DISAGREEMENT_THRESHOLD,
                label_quality=label_quality,
                exported_at=None,
                export_batch_id=None,
            )
            db.add(label)
            return

        label.grading_run_id = grading_run.id
        label.session_id = source_session.id
        label.manager_id = reviewer.id
        label.org_id = reviewer.org_id
        label.ai_overall_score = float(scorecard.overall_score)
        label.ai_category_scores = dict(scorecard.category_scores or {})
        label.override_overall_score = review.override_score
        label.override_reason_text = review.notes
        label.override_delta_overall = delta
        label.is_high_disagreement = delta >= DISAGREEMENT_THRESHOLD
        label.label_quality = label_quality

    def _emit_disagreement_alert(
        self,
        db: Session,
        *,
        review: ManagerReview,
        reviewer: User,
        scorecard: Scorecard,
        source_session: DrillSession,
        grading_run: GradingRun | None,
        delta: float,
    ) -> None:
        rep = db.get(User, source_session.rep_id)
        alert_key = f"grading-disagreement-{review.id}"
        occurred_at = review.reviewed_at or datetime.now(timezone.utc)
        severity = "high" if delta >= 3.5 else "medium"
        title = f"Large grading disagreement for {rep.name if rep else 'rep'}"
        description = (
            f"AI scored {scorecard.overall_score:.1f}; manager override was {review.override_score:.1f} "
            f"({delta:.1f} point delta)."
        )

        for period_key in ALERT_PERIODS:
            row = db.scalar(
                select(AnalyticsFactAlert).where(
                    AnalyticsFactAlert.manager_id == reviewer.id,
                    AnalyticsFactAlert.period_key == period_key,
                    AnalyticsFactAlert.alert_key == alert_key,
                )
            )
            if row is None:
                row = AnalyticsFactAlert(
                    alert_key=alert_key,
                    manager_id=reviewer.id,
                    org_id=reviewer.org_id,
                    team_id=rep.team_id if rep else reviewer.team_id,
                    period_key=period_key,
                    severity=severity,
                    kind="grading_disagreement",
                    title=title,
                    description=description,
                    occurred_at=occurred_at,
                    rep_id=rep.id if rep else source_session.rep_id,
                    scenario_id=source_session.scenario_id,
                    session_id=source_session.id,
                    focus_turn_id=None,
                    baseline_value=scorecard.overall_score,
                    observed_value=review.override_score,
                    delta=delta,
                    z_score=None,
                    is_active=True,
                    first_seen_at=occurred_at,
                    last_seen_at=occurred_at,
                    metadata_json={},
                )
                db.add(row)

            row.severity = severity
            row.kind = "grading_disagreement"
            row.title = title
            row.description = description
            row.team_id = rep.team_id if rep else reviewer.team_id
            row.rep_id = rep.id if rep else source_session.rep_id
            row.scenario_id = source_session.scenario_id
            row.session_id = source_session.id
            row.baseline_value = scorecard.overall_score
            row.observed_value = review.override_score
            row.delta = delta
            row.is_active = True
            row.occurred_at = occurred_at
            row.last_seen_at = occurred_at
            row.metadata_json = {
                "review_id": review.id,
                "reviewer_id": reviewer.id,
                "rep_name": rep.name if rep else None,
                "prompt_version_id": grading_run.prompt_version_id if grading_run else None,
                "scorecard_id": scorecard.id,
                "session_id": source_session.id,
                "ai_score": scorecard.overall_score,
                "override_score": review.override_score,
                "delta": delta,
            }

    def recent(self, db: Session, *, manager_id: str, limit: int = 50) -> list[ManagerActionLog]:
        limit = max(1, min(limit, 200))
        stmt = (
            select(ManagerActionLog)
            .where(ManagerActionLog.manager_id == manager_id)
            .order_by(ManagerActionLog.occurred_at.desc())
            .limit(limit)
        )
        return db.scalars(stmt).all()
