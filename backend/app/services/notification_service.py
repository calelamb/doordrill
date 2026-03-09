from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assignment import Assignment
from app.models.device_token import DeviceToken
from app.models.notification_delivery import NotificationDelivery
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.user import User
from app.services.notification_providers import (
    ExpoPushProvider,
    FcmPushProvider,
    LogEmailProvider,
    LogPushProvider,
    SendGridEmailProvider,
    SesEmailProvider,
)

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.email_provider = self._build_email_provider()
        self.push_provider = self._build_push_provider()

    def _build_email_provider(self):
        provider_name = (self.settings.notification_email_provider or "sendgrid").lower()
        if provider_name == "ses":
            return SesEmailProvider(self.settings)
        if provider_name == "sendgrid":
            return SendGridEmailProvider(self.settings)
        return LogEmailProvider()

    def _build_push_provider(self):
        provider_name = (self.settings.notification_push_provider or "expo").lower()
        if provider_name == "fcm":
            return FcmPushProvider(self.settings)
        if provider_name == "expo":
            return ExpoPushProvider(self.settings)
        return LogPushProvider()

    def _infer_push_provider(self, token: str) -> str:
        if token.startswith("ExponentPushToken["):
            return "expo"
        return (self.settings.notification_push_provider or "expo").lower()

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
            manager_tokens = db.scalars(
                select(DeviceToken).where(DeviceToken.user_id == manager.id, DeviceToken.status == "active")
            ).all()
            for token in manager_tokens:
                push_payload = {
                    "token_id": token.id,
                    "push_token": token.token,
                    "provider": token.provider,
                    "title": "DoorDrill Session Completed",
                    "body": summary,
                    "data": {"session_id": session_id, "rep_id": session.rep_id},
                }
                delivery = NotificationDelivery(
                    session_id=session_id,
                    manager_id=manager.id,
                    channel="push",
                    payload=push_payload,
                    provider_response={},
                    status="queued",
                    retries=0,
                )
                db.add(delivery)
                db.flush()
                result = await self._deliver(db, delivery)
                results.append(result)

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

    async def _deliver(self, db: Session, delivery: NotificationDelivery) -> dict[str, Any]:
        if delivery.channel == "email":
            send_result = await self.email_provider.send(
                to_email=str(delivery.payload.get("to_email", "")),
                subject=str(delivery.payload.get("subject", "DoorDrill Notification")),
                body=str(delivery.payload.get("body", "")),
            )
        elif delivery.channel == "push":
            send_result = await self.push_provider.send(
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
                    token_row.status = "invalid"

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
        provider: str | None,
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
