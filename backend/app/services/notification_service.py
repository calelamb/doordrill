from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assignment import Assignment
from app.models.device_token import DeviceToken
from app.models.notification_delivery import NotificationDelivery
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.types import AssignmentStatus, UserRole
from app.models.user import User
from app.services.notification_providers import (
    ExpoPushProvider,
    FcmPushProvider,
    LogEmailProvider,
    LogPushProvider,
    PushProvider,
    SendGridEmailProvider,
    SesEmailProvider,
)

logger = logging.getLogger(__name__)
REP_NOTIFICATION_PREFERENCE_KEYS = (
    "score_ready",
    "assignment_created",
    "assignment_due_soon",
    "coaching_note",
    "streak_nudge",
)


def _normalize_rep_notification_preferences(raw_preferences: Any) -> dict[str, bool]:
    normalized = {key: True for key in REP_NOTIFICATION_PREFERENCE_KEYS}
    if not isinstance(raw_preferences, dict):
        return normalized
    for key in REP_NOTIFICATION_PREFERENCE_KEYS:
        value = raw_preferences.get(key)
        if isinstance(value, bool):
            normalized[key] = value
    return normalized


class NotificationService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.email_provider = self._build_email_provider()
        self.push_providers = self._build_push_providers()
        self.push_provider = self._get_push_provider(self.settings.notification_push_provider)

    def _build_email_provider(self):
        provider_name = (self.settings.notification_email_provider or "sendgrid").lower()
        if provider_name == "ses":
            return SesEmailProvider(self.settings)
        if provider_name == "sendgrid":
            return SendGridEmailProvider(self.settings)
        return LogEmailProvider()

    def _build_push_providers(self) -> dict[str, PushProvider]:
        return {
            "expo": ExpoPushProvider(self.settings),
            "fcm": FcmPushProvider(self.settings),
            "log": LogPushProvider(),
        }

    def _get_push_provider(self, provider_name: str | None) -> PushProvider:
        normalized = (provider_name or "").strip().lower()
        if normalized:
            fallback = self.push_provider if hasattr(self, "push_provider") else self.push_providers["log"]
            return self.push_providers.get(normalized, fallback)
        if hasattr(self, "push_provider"):
            return self.push_provider
        default_name = (self.settings.notification_push_provider or "expo").lower()
        return self.push_providers.get(default_name, self.push_providers["log"])

    def _infer_push_provider(self, token: str) -> str:
        if token.startswith("ExponentPushToken["):
            return "expo"
        return (self.settings.notification_push_provider or "expo").lower()

    @staticmethod
    def _format_month_day(value: datetime) -> str:
        return value.strftime("%b %d").replace(" 0", " ")

    @staticmethod
    def _format_month_day_time(value: datetime) -> str:
        return value.strftime("%b %d at %I%p").replace(" 0", " ")

    async def _get_active_tokens(self, db: Session, *, user_id: str) -> list[DeviceToken]:
        return db.scalars(
            select(DeviceToken).where(
                DeviceToken.user_id == user_id,
                DeviceToken.status == "active",
            )
        ).all()

    async def _is_notif_enabled(self, db: Session, *, user_id: str, notif_type: str) -> bool:
        if db is None:
            return True
        user = db.get(User, user_id)
        if user is None or user.role != UserRole.REP:
            return True
        preferences = _normalize_rep_notification_preferences(user.notification_preferences)
        return preferences.get(notif_type, True)

    async def _send_to_tokens(
        self,
        db: Session,
        *,
        tokens: list[DeviceToken],
        title: str,
        body: str,
        data: dict[str, Any],
        user_id: str,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for token in tokens:
            delivery = NotificationDelivery(
                session_id=session_id,
                manager_id=user_id,
                channel="push",
                payload={
                    "token_id": token.id,
                    "push_token": token.token,
                    "provider": token.provider,
                    "title": title,
                    "body": body,
                    "data": data,
                },
                provider_response={},
                status="queued",
                retries=0,
            )
            db.add(delivery)
            db.flush()
            results.append(await self._deliver(db, delivery))

        if results:
            db.commit()
        return results

    async def notify_manager_session_completed(self, db: Session, session_id: str) -> dict:
        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        if session is None:
            return {"sent": False, "reason": "session_not_found"}

        assignment = db.scalar(select(Assignment).where(Assignment.id == session.assignment_id))
        if assignment is None:
            return {"sent": False, "reason": "assignment_not_found"}

        manager = db.scalar(select(User).where(User.id == assignment.assigned_by))
        rep = db.scalar(select(User).where(User.id == session.rep_id))
        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        if manager is None:
            return {"sent": False, "reason": "manager_not_found"}

        summary = (
            f"Session {session_id} completed for rep {rep.name if rep else session.rep_id}; "
            f"score={scorecard.overall_score if scorecard else 'pending'}"
        )

        results: list[dict[str, Any]] = []
        if self.settings.manager_notification_email_enabled:
            email_payload = {
                "to_email": manager.email,
                "subject": "DoorDrill Session Completed",
                "body": summary,
                "session_id": session_id,
                "rep_id": session.rep_id,
            }
            delivery = NotificationDelivery(
                session_id=session_id,
                manager_id=manager.id,
                channel="email",
                payload=email_payload,
                provider_response={},
                status="queued",
                retries=0,
            )
            db.add(delivery)
            db.flush()
            result = await self._deliver(db, delivery)
            results.append(result)

        if self.settings.manager_notification_push_enabled:
            manager_tokens = await self._get_active_tokens(db, user_id=manager.id)
            results.extend(
                await self._send_to_tokens(
                    db,
                    tokens=manager_tokens,
                    title="DoorDrill Session Completed",
                    body=summary,
                    data={"session_id": session_id, "rep_id": session.rep_id},
                    user_id=manager.id,
                    session_id=session_id,
                )
            )

        db.commit()

        logger.info(
            "manager_session_notification",
            extra={
                "session_id": session_id,
                "manager_id": manager.id,
                "manager_email": manager.email,
                "summary": summary,
                "delivery_count": len(results),
                "channels": [result.get("channel") for result in results],
            },
        )
        return {
            "sent": any(result.get("sent") for result in results),
            "deliveries": results,
            "manager_id": manager.id,
            "manager_email": manager.email,
            "summary": summary,
        }

    async def notify_rep_score_ready(
        self,
        db: Session,
        *,
        rep_id: str,
        session_id: str,
        scenario_name: str,
        overall_score: float,
    ) -> None:
        if not await self._is_notif_enabled(db, user_id=rep_id, notif_type="score_ready"):
            return None
        tokens = await self._get_active_tokens(db, user_id=rep_id)
        if not tokens:
            return None

        score_display = f"{overall_score:.1f}/10"
        emoji = "🟢" if overall_score >= 8 else "🟡" if overall_score >= 5 else "🔴"
        title = f"{emoji} Drill Results Ready"
        body = f"You scored {score_display} on {scenario_name}. Tap to review."
        data = {"type": "score_ready", "session_id": session_id}

        await self._send_to_tokens(
            db,
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            user_id=rep_id,
            session_id=session_id,
        )
        return None

    async def notify_rep_assignment_created(
        self,
        db: Session,
        *,
        rep_id: str,
        assignment_id: str,
        scenario_name: str,
        due_at: datetime | None,
    ) -> None:
        if not await self._is_notif_enabled(db, user_id=rep_id, notif_type="assignment_created"):
            return None
        tokens = await self._get_active_tokens(db, user_id=rep_id)
        if not tokens:
            return None

        title = "📋 New Drill Assigned"
        due_str = f" Due {self._format_month_day(due_at)}." if due_at else ""
        body = f"{scenario_name} has been assigned to you.{due_str}"
        data = {"type": "assignment_created", "assignment_id": assignment_id}

        await self._send_to_tokens(
            db,
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            user_id=rep_id,
        )
        return None

    async def notify_rep_assignment_due_soon(
        self,
        db: Session,
        *,
        rep_id: str,
        assignment_id: str,
        scenario_name: str,
        due_at: datetime,
    ) -> None:
        if not await self._is_notif_enabled(db, user_id=rep_id, notif_type="assignment_due_soon"):
            return None
        tokens = await self._get_active_tokens(db, user_id=rep_id)
        if not tokens:
            return None

        title = "⏰ Drill Due Tomorrow"
        body = f"'{scenario_name}' is due {self._format_month_day_time(due_at)}. Get it done!"
        data = {"type": "assignment_due_soon", "assignment_id": assignment_id}

        await self._send_to_tokens(
            db,
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            user_id=rep_id,
        )
        return None

    async def notify_rep_coaching_note(
        self,
        db: Session,
        *,
        rep_id: str,
        session_id: str,
        manager_name: str,
        note_preview: str,
    ) -> None:
        if not await self._is_notif_enabled(db, user_id=rep_id, notif_type="coaching_note"):
            return None
        tokens = await self._get_active_tokens(db, user_id=rep_id)
        if not tokens:
            return None

        title = f"💬 Note from {manager_name}"
        body = note_preview[:80] + ("…" if len(note_preview) > 80 else "")
        data = {"type": "coaching_note", "session_id": session_id}

        await self._send_to_tokens(
            db,
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            user_id=rep_id,
            session_id=session_id,
        )
        return None

    async def notify_rep_streak_nudge(
        self,
        db: Session,
        *,
        rep_id: str,
        days_inactive: int,
        last_score: float | None,
    ) -> None:
        if not await self._is_notif_enabled(db, user_id=rep_id, notif_type="streak_nudge"):
            return None
        tokens = await self._get_active_tokens(db, user_id=rep_id)
        if not tokens:
            return None

        title = "🔥 Keep Your Streak Going"
        if last_score is not None and last_score < 7.0:
            body = (
                f"You haven't drilled in {days_inactive} days. "
                f"Your last score was {last_score:.1f} — there's room to improve!"
            )
        else:
            body = f"You haven't drilled in {days_inactive} days. Stay sharp — run a quick drill today."
        data = {"type": "streak_nudge"}

        await self._send_to_tokens(
            db,
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            user_id=rep_id,
        )
        return None

    async def send_assignment_due_soon_reminders(
        self,
        db: Session,
        *,
        now: datetime | None = None,
        window_start_hours: int = 20,
        window_end_hours: int = 28,
    ) -> dict[str, Any]:
        reference_time = now or datetime.now(timezone.utc)
        window_start = reference_time + timedelta(hours=window_start_hours)
        window_end = reference_time + timedelta(hours=window_end_hours)
        rows = db.execute(
            select(Assignment, Scenario)
            .join(Scenario, Scenario.id == Assignment.scenario_id)
            .where(
                Assignment.due_at.is_not(None),
                Assignment.due_at >= window_start,
                Assignment.due_at <= window_end,
                Assignment.status.in_([AssignmentStatus.ASSIGNED, AssignmentStatus.IN_PROGRESS]),
                Assignment.due_soon_notified_at.is_(None),
            )
            .order_by(Assignment.due_at.asc())
        ).all()

        notified_assignment_ids: list[str] = []
        skipped_assignment_ids: list[str] = []
        suppressed_assignment_ids: list[str] = []
        for assignment, scenario in rows:
            if not await self._is_notif_enabled(db, user_id=assignment.rep_id, notif_type="assignment_due_soon"):
                assignment.due_soon_notified_at = reference_time
                suppressed_assignment_ids.append(assignment.id)
                skipped_assignment_ids.append(assignment.id)
                continue
            tokens = await self._get_active_tokens(db, user_id=assignment.rep_id)
            if not tokens:
                skipped_assignment_ids.append(assignment.id)
                continue

            await self.notify_rep_assignment_due_soon(
                db,
                rep_id=assignment.rep_id,
                assignment_id=assignment.id,
                scenario_name=scenario.name,
                due_at=assignment.due_at,
            )
            assignment.due_soon_notified_at = reference_time
            notified_assignment_ids.append(assignment.id)

        if notified_assignment_ids or suppressed_assignment_ids:
            db.commit()

        return {
            "processed_count": len(rows),
            "notified_count": len(notified_assignment_ids),
            "notified_assignment_ids": notified_assignment_ids,
            "skipped_assignment_ids": skipped_assignment_ids,
            "suppressed_assignment_ids": suppressed_assignment_ids,
        }

    async def send_streak_nudges(
        self,
        db: Session,
        *,
        now: datetime | None = None,
        thresholds: tuple[int, ...] = (2, 4, 7),
    ) -> dict[str, Any]:
        reference_time = now or datetime.now(timezone.utc)
        notifications: list[dict[str, Any]] = []

        for days in thresholds:
            upper_bound = reference_time - timedelta(days=days)
            lower_bound = reference_time - timedelta(days=days + 1)
            last_drill = func.max(DrillSession.started_at)
            rows = db.execute(
                select(User.id, last_drill.label("last_drill"))
                .join(DrillSession, DrillSession.rep_id == User.id)
                .where(User.role == UserRole.REP)
                .group_by(User.id)
                .having(last_drill <= upper_bound, last_drill > lower_bound)
            ).all()

            for rep_id, _ in rows:
                if not await self._is_notif_enabled(db, user_id=rep_id, notif_type="streak_nudge"):
                    continue
                last_score = await self._get_last_score(db, rep_id=rep_id)
                await self.notify_rep_streak_nudge(
                    db,
                    rep_id=rep_id,
                    days_inactive=days,
                    last_score=last_score,
                )
                notifications.append({"rep_id": rep_id, "days_inactive": days, "last_score": last_score})

        return {"nudged_count": len(notifications), "items": notifications}

    async def _get_last_score(self, db: Session, *, rep_id: str) -> float | None:
        row = db.execute(
            select(Scorecard.overall_score)
            .join(DrillSession, DrillSession.id == Scorecard.session_id)
            .where(DrillSession.rep_id == rep_id)
            .order_by(DrillSession.started_at.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        score = row[0]
        return float(score) if score is not None else None

    async def _deliver(self, db: Session, delivery: NotificationDelivery) -> dict[str, Any]:
        if delivery.channel == "email":
            send_result = await self.email_provider.send(
                to_email=str(delivery.payload.get("to_email", "")),
                subject=str(delivery.payload.get("subject", "DoorDrill Notification")),
                body=str(delivery.payload.get("body", "")),
            )
        elif delivery.channel == "push":
            provider = self._get_push_provider(str(delivery.payload.get("provider") or ""))
            send_result = await provider.send(
                push_token=str(delivery.payload.get("push_token", "")),
                title=str(delivery.payload.get("title", "DoorDrill")),
                body=str(delivery.payload.get("body", "")),
                data=delivery.payload.get("data", {}),
            )
        else:
            send_result = None

        now = datetime.now(timezone.utc)
        if send_result and send_result.ok:
            delivery.status = "sent"
            delivery.sent_at = now
            delivery.next_retry_at = None
            delivery.provider_response = send_result.response
            delivery.last_error = None
            return {"id": delivery.id, "channel": delivery.channel, "sent": True}

        delivery.retries += 1
        delivery.provider_response = send_result.response if send_result else {}
        delivery.last_error = send_result.error if send_result else "unsupported_channel"
        permanent_failure = bool(send_result and send_result.permanent_failure)
        invalid_token = bool(send_result and send_result.invalid_token)

        if invalid_token and delivery.channel == "push":
            token_id = str(delivery.payload.get("token_id") or "").strip()
            if token_id:
                token_row = db.scalar(select(DeviceToken).where(DeviceToken.id == token_id))
                if token_row is not None:
                    token_row.status = "revoked"

        if permanent_failure or delivery.retries >= self.settings.notification_max_retries:
            delivery.status = "dead_letter"
            delivery.next_retry_at = None
        else:
            delay_seconds = self.settings.notification_retry_base_seconds * (2 ** max(0, delivery.retries - 1))
            delivery.next_retry_at = now + timedelta(seconds=min(delay_seconds, 3600))
            delivery.status = "retry_scheduled"
        return {
            "id": delivery.id,
            "channel": delivery.channel,
            "sent": False,
            "status": delivery.status,
            "error": delivery.last_error,
        }

    def register_device_token(
        self,
        db: Session,
        *,
        user_id: str,
        platform: str,
        provider: str | None = None,
        token: str,
    ) -> DeviceToken:
        resolved_provider = provider or self._infer_push_provider(token)
        now = datetime.now(timezone.utc)

        row_filter = (
            DeviceToken.user_id == user_id,
            DeviceToken.provider == resolved_provider,
            DeviceToken.token == token,
        )
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        if dialect_name in {"postgresql", "sqlite"}:
            insert_fn = postgresql_insert if dialect_name == "postgresql" else sqlite_insert
            stmt = insert_fn(DeviceToken).values(
                user_id=user_id,
                platform=platform,
                provider=resolved_provider,
                token=token,
                status="active",
                last_seen_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "provider", "token"],
                set_={
                    "platform": platform,
                    "status": "active",
                    "last_seen_at": now,
                },
            )
            db.execute(stmt)
            db.commit()
            row = db.scalar(select(DeviceToken).where(*row_filter))
            if row is None:
                raise RuntimeError("device token upsert failed")
            return row

        row = DeviceToken(
            user_id=user_id,
            platform=platform,
            provider=resolved_provider,
            token=token,
            status="active",
            last_seen_at=now,
        )
        existing = db.scalar(select(DeviceToken).where(*row_filter))
        if existing:
            existing.platform = platform
            existing.status = "active"
            existing.last_seen_at = now
            db.commit()
            db.refresh(existing)
            return existing

        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def revoke_device_token(self, db: Session, *, user_id: str, token_id: str) -> bool:
        row = db.scalar(select(DeviceToken).where(DeviceToken.id == token_id, DeviceToken.user_id == user_id))
        if row is None:
            return False
        row.status = "revoked"
        db.commit()
        return True

    async def retry_due_deliveries(self, db: Session, *, limit: int = 50) -> dict[str, Any]:
        stmt = (
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "retry_scheduled",
                NotificationDelivery.next_retry_at.is_not(None),
                NotificationDelivery.next_retry_at <= datetime.now(timezone.utc),
            )
            .order_by(NotificationDelivery.next_retry_at.asc())
            .limit(limit)
        )
        bind = db.get_bind()
        if bind is not None and bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update(skip_locked=True)

        rows = db.scalars(stmt).all()
        items: list[dict[str, Any]] = []
        for row in rows:
            if row.status == "dead_letter":
                continue
            items.append(await self._deliver(db, row))
        db.commit()
        return {"retried_count": len(items), "items": items}

    def list_manager_notifications(
        self,
        db: Session,
        *,
        manager_id: str,
        status: str | None = None,
        channel: str | None = None,
        session_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
    ) -> list[NotificationDelivery]:
        stmt = select(NotificationDelivery).where(NotificationDelivery.manager_id == manager_id)
        if status:
            stmt = stmt.where(NotificationDelivery.status == status)
        if channel:
            stmt = stmt.where(NotificationDelivery.channel == channel)
        if session_id:
            stmt = stmt.where(NotificationDelivery.session_id == session_id)
        if date_from:
            stmt = stmt.where(NotificationDelivery.created_at >= date_from)
        if date_to:
            stmt = stmt.where(NotificationDelivery.created_at <= date_to)
        return db.scalars(stmt.order_by(NotificationDelivery.created_at.desc()).limit(limit)).all()
