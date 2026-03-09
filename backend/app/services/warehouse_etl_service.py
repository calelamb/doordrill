from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.prompt_version import PromptVersion
from app.models.scenario import Scenario
from app.models.scorecard import ManagerCoachingNote, ManagerReview, Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.user import Organization, User
from app.models.warehouse import DimRep, DimScenario, DimTime, FactRepDaily, FactSession
from app.models.types import TurnSpeaker, UserRole
from app.services.predictive_modeling_service import PredictiveModelingService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _month_start(value: datetime | None) -> date | None:
    normalized = _normalize_dt(value)
    if normalized is None:
        return None
    return date(normalized.year, normalized.month, 1)


@dataclass
class SessionWarehouseBundle:
    session: DrillSession
    assignment: Assignment
    rep: User
    manager: User
    organization: Organization | None
    scenario: Scenario
    scorecard: Scorecard
    turns: list[SessionTurn]
    reviews: list[ManagerReview]
    coaching_notes: list[ManagerCoachingNote]
    grading_run: GradingRun | None


class WarehouseEtlService:
    ETL_VERSION = "1.0"

    def __init__(self) -> None:
        self.predictive_modeling_service = PredictiveModelingService()

    def write_session(self, db: Session, session_id: str, *, commit: bool = True) -> dict[str, str]:
        bundle = self._load_session_with_relations(db, session_id)
        self._upsert_dim_time(db, self._session_date(bundle.session))
        self._upsert_dim_rep(db, bundle)
        self._upsert_dim_scenario(db, bundle)
        fact = self._upsert_fact_session(db, bundle)
        self._upsert_fact_rep_daily(db, bundle, fact)
        if commit:
            db.commit()
        else:
            db.flush()
        return {"session_id": fact.session_id, "fact_session_id": fact.fact_session_id}

    def refresh_predictive_aggregates(self, db: Session, *, org_id: str | None = None) -> dict[str, int]:
        scenario_rows_written = self.predictive_modeling_service.refresh_scenario_outcome_aggregates(db, org_id=org_id)
        org_ids = (
            [org_id]
            if org_id is not None
            else [
                value
                for value in db.scalars(
                    select(func.distinct(User.org_id)).where(
                        User.org_id.is_not(None),
                        User.role == UserRole.REP,
                    )
                ).all()
                if value
            ]
        )
        cohort_rows_written = 0
        for current_org_id in org_ids:
            cohort_rows_written += self.predictive_modeling_service.refresh_cohort_benchmarks(
                db,
                org_id=current_org_id,
            )
        return {
            "scenario_outcome_aggregate_rows": scenario_rows_written,
            "rep_cohort_benchmark_rows": cohort_rows_written,
        }

    def _load_session_with_relations(self, db: Session, session_id: str) -> SessionWarehouseBundle:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        if session is None:
            raise ValueError("session not found")

        assignment = db.scalar(select(Assignment).where(Assignment.id == session.assignment_id))
        if assignment is None:
            raise ValueError("assignment not found")

        rep = db.scalar(select(User).where(User.id == session.rep_id))
        if rep is None:
            raise ValueError("rep not found")

        manager = db.scalar(select(User).where(User.id == assignment.assigned_by))
        if manager is None:
            raise ValueError("manager not found")

        scenario = db.scalar(select(Scenario).where(Scenario.id == session.scenario_id))
        if scenario is None:
            raise ValueError("scenario not found")

        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        if scorecard is None:
            raise ValueError("session has no scorecard - grade before warehouse write")

        organization = db.scalar(select(Organization).where(Organization.id == rep.org_id))
        turns = db.scalars(select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())).all()
        reviews = db.scalars(
            select(ManagerReview).where(ManagerReview.scorecard_id == scorecard.id).order_by(ManagerReview.reviewed_at.desc())
        ).all()
        coaching_notes = db.scalars(
            select(ManagerCoachingNote).where(ManagerCoachingNote.scorecard_id == scorecard.id).order_by(ManagerCoachingNote.created_at.desc())
        ).all()
        grading_run = db.scalar(
            select(GradingRun)
            .where(GradingRun.session_id == session_id)
            .order_by(GradingRun.completed_at.desc(), GradingRun.created_at.desc())
        )

        return SessionWarehouseBundle(
            session=session,
            assignment=assignment,
            rep=rep,
            manager=manager,
            organization=organization,
            scenario=scenario,
            scorecard=scorecard,
            turns=turns,
            reviews=reviews,
            coaching_notes=coaching_notes,
            grading_run=grading_run,
        )

    def _session_date(self, session: DrillSession) -> date:
        started = _normalize_dt(session.started_at) or _utcnow()
        return started.date()

    def _upsert_dim_time(self, db: Session, day_value: date) -> DimTime:
        row = db.get(DimTime, day_value)
        day_of_week = (day_value.weekday() + 1) % 7
        if row is None:
            row = DimTime(
                date_key=day_value,
                day_of_week=day_of_week,
                week_number=int(day_value.isocalendar().week),
                month=day_value.month,
                quarter=((day_value.month - 1) // 3) + 1,
                year=day_value.year,
                is_weekday=day_of_week not in {0, 6},
            )
            db.add(row)
            return row

        row.day_of_week = day_of_week
        row.week_number = int(day_value.isocalendar().week)
        row.month = day_value.month
        row.quarter = ((day_value.month - 1) // 3) + 1
        row.year = day_value.year
        row.is_weekday = day_of_week not in {0, 6}
        return row

    def _upsert_dim_rep(self, db: Session, bundle: SessionWarehouseBundle) -> DimRep:
        first_session_at = db.scalar(select(func.min(DrillSession.started_at)).where(DrillSession.rep_id == bundle.rep.id))
        last_session_at = db.scalar(select(func.max(DrillSession.started_at)).where(DrillSession.rep_id == bundle.rep.id))
        total_sessions = int(db.scalar(select(func.count(DrillSession.id)).where(DrillSession.rep_id == bundle.rep.id)) or 0)

        row = db.get(DimRep, bundle.rep.id)
        if row is None:
            row = DimRep(
                rep_id=bundle.rep.id,
                org_id=bundle.rep.org_id,
                team_id=bundle.rep.team_id,
                rep_name=bundle.rep.name,
                hire_cohort=_month_start(first_session_at),
                industry=bundle.organization.industry if bundle.organization is not None else None,
                is_active=True,
                first_session_at=_normalize_dt(first_session_at),
                last_session_at=_normalize_dt(last_session_at),
                total_sessions=total_sessions,
                last_refreshed_at=_utcnow(),
            )
            db.add(row)
            return row

        row.org_id = bundle.rep.org_id
        row.team_id = bundle.rep.team_id
        row.rep_name = bundle.rep.name
        row.hire_cohort = _month_start(first_session_at)
        row.industry = bundle.organization.industry if bundle.organization is not None else None
        row.is_active = True
        row.first_session_at = _normalize_dt(first_session_at)
        row.last_session_at = _normalize_dt(last_session_at)
        row.total_sessions = total_sessions
        row.last_refreshed_at = _utcnow()
        return row

    def _upsert_dim_scenario(self, db: Session, bundle: SessionWarehouseBundle) -> DimScenario:
        persona = bundle.scenario.persona if isinstance(bundle.scenario.persona, dict) else {}
        objection_focus = persona.get("objection_queue") or persona.get("concerns") or []
        if not isinstance(objection_focus, list):
            objection_focus = []
        objection_focus = [str(item).strip() for item in objection_focus if str(item).strip()]

        row = db.get(DimScenario, bundle.scenario.id)
        if row is None:
            row = DimScenario(
                scenario_id=bundle.scenario.id,
                org_id=bundle.scenario.org_id,
                scenario_name=bundle.scenario.name,
                industry=bundle.scenario.industry,
                difficulty=bundle.scenario.difficulty,
                objection_focus=list(dict.fromkeys(objection_focus)),
                created_by_id=bundle.scenario.created_by_id,
                is_active=True,
                last_refreshed_at=_utcnow(),
            )
            db.add(row)
            return row

        row.org_id = bundle.scenario.org_id
        row.scenario_name = bundle.scenario.name
        row.industry = bundle.scenario.industry
        row.difficulty = bundle.scenario.difficulty
        row.objection_focus = list(dict.fromkeys(objection_focus))
        row.created_by_id = bundle.scenario.created_by_id
        row.is_active = True
        row.last_refreshed_at = _utcnow()
        return row

    def _upsert_fact_session(self, db: Session, bundle: SessionWarehouseBundle) -> FactSession:
        now = _utcnow()
        session_date = self._session_date(bundle.session)
        rep_turns = [turn for turn in bundle.turns if turn.speaker == TurnSpeaker.REP]
        ai_turns = [turn for turn in bundle.turns if turn.speaker == TurnSpeaker.AI]
        objection_tags = sorted(
            {
                tag
                for turn in bundle.turns
                for tag in (turn.objection_tags or [])
                if isinstance(tag, str) and tag.strip()
            }
        )
        barge_in_count = sum(1 for turn in bundle.turns if turn.mb_interruption_type)
        avg_rep_turn_length_chars = (
            round(mean(len((turn.text or "").strip()) for turn in rep_turns), 2) if rep_turns else None
        )
        final_emotion = next((turn.emotion_after for turn in reversed(bundle.turns) if turn.emotion_after), None)
        latest_review = bundle.reviews[0] if bundle.reviews else None
        weakness_tags = list(bundle.scorecard.weakness_tags or [])[:3]
        category_scores = bundle.scorecard.category_scores if isinstance(bundle.scorecard.category_scores, dict) else {}

        row = db.scalar(select(FactSession).where(FactSession.session_id == bundle.session.id))
        values = {
            "session_id": bundle.session.id,
            "org_id": bundle.rep.org_id,
            "manager_id": bundle.manager.id,
            "rep_id": bundle.rep.id,
            "scenario_id": bundle.scenario.id,
            "session_date": session_date,
            "started_at": _normalize_dt(bundle.session.started_at),
            "ended_at": _normalize_dt(bundle.session.ended_at),
            "duration_seconds": bundle.session.duration_seconds,
            "status": bundle.session.status.value if hasattr(bundle.session.status, "value") else str(bundle.session.status),
            "overall_score": bundle.scorecard.overall_score,
            "score_opening": self._score_value(category_scores.get("opening")),
            "score_pitch_delivery": self._score_value(category_scores.get("pitch_delivery")),
            "score_objection_handling": self._score_value(category_scores.get("objection_handling")),
            "score_closing_technique": self._score_value(category_scores.get("closing_technique")),
            "score_professionalism": self._score_value(category_scores.get("professionalism")),
            "grading_confidence": bundle.grading_run.confidence_score if bundle.grading_run is not None else None,
            "prompt_version_id": bundle.grading_run.prompt_version_id if bundle.grading_run is not None else None,
            "turn_count": len(bundle.turns),
            "rep_turn_count": len(rep_turns),
            "ai_turn_count": len(ai_turns),
            "objection_count": len(objection_tags),
            "barge_in_count": barge_in_count,
            "avg_rep_turn_length_chars": avg_rep_turn_length_chars,
            "final_emotion": final_emotion,
            "has_manager_review": bool(bundle.reviews),
            "override_score": latest_review.override_score if latest_review is not None else None,
            "override_delta": (
                round(abs(float(latest_review.override_score) - float(bundle.scorecard.overall_score)), 2)
                if latest_review is not None and latest_review.override_score is not None and bundle.scorecard.overall_score is not None
                else None
            ),
            "has_coaching_note": bool(bundle.coaching_notes),
            "weakness_tag_1": weakness_tags[0] if len(weakness_tags) > 0 else None,
            "weakness_tag_2": weakness_tags[1] if len(weakness_tags) > 1 else None,
            "weakness_tag_3": weakness_tags[2] if len(weakness_tags) > 2 else None,
            "etl_version": self.ETL_VERSION,
            "etl_written_at": now,
        }

        if row is None:
            row = FactSession(**values)
            db.add(row)
            db.flush()
            return row

        for key, value in values.items():
            setattr(row, key, value)
        db.flush()
        return row

    def _upsert_fact_rep_daily(self, db: Session, bundle: SessionWarehouseBundle, _: FactSession) -> FactRepDaily:
        session_date = self._session_date(bundle.session)
        rows = db.scalars(
            select(FactSession).where(
                FactSession.rep_id == bundle.rep.id,
                FactSession.manager_id == bundle.manager.id,
                FactSession.session_date == session_date,
            )
        ).all()
        scores = [row.overall_score for row in rows if row.overall_score is not None]
        objection_scores = [row.score_objection_handling for row in rows if row.score_objection_handling is not None]
        closing_scores = [row.score_closing_technique for row in rows if row.score_closing_technique is not None]

        row = db.scalar(
            select(FactRepDaily).where(
                FactRepDaily.rep_id == bundle.rep.id,
                FactRepDaily.session_date == session_date,
            )
        )
        values = {
            "rep_id": bundle.rep.id,
            "org_id": bundle.rep.org_id,
            "manager_id": bundle.manager.id,
            "session_date": session_date,
            "session_count": len(rows),
            "scored_count": len(scores),
            "avg_score": round(mean(scores), 2) if scores else None,
            "min_score": min(scores) if scores else None,
            "max_score": max(scores) if scores else None,
            "avg_objection_handling": round(mean(objection_scores), 2) if objection_scores else None,
            "avg_closing_technique": round(mean(closing_scores), 2) if closing_scores else None,
            "total_duration_seconds": int(sum(row.duration_seconds or 0 for row in rows)),
            "barge_in_count": int(sum(row.barge_in_count for row in rows)),
            "override_count": sum(1 for row in rows if row.has_manager_review),
            "coaching_note_count": sum(1 for row in rows if row.has_coaching_note),
        }

        if row is None:
            row = FactRepDaily(**values)
            db.add(row)
            db.flush()
            return row

        for key, value in values.items():
            setattr(row, key, value)
        db.flush()
        return row

    def _score_value(self, value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            raw = value.get("score")
            if isinstance(raw, (int, float)):
                return float(raw)
        return None
