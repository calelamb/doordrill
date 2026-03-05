from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assignment import Assignment
from app.models.device_token import DeviceToken
from app.models.notification_delivery import NotificationDelivery
from app.models.scorecard import Scorecard
from app.models.session import Session
from app.models.user import User
from app.services.notification_providers import ExpoPushProvider, SendGridEmailProvider

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.email_provider = SendGridEmailProvider(self.settings)
        self.push_provider = ExpoPushProvider(self.settings)

    async def notify_manager_session_completed(self, db: Session, session_id: str) -> dict:
        session = db.scalar(select(Session).where(Session.id == session_id))
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
        delay_seconds = self.settings.notification_retry_base_seconds * (2 ** max(0, delivery.retries - 1))
        delivery.next_retry_at = now + timedelta(seconds=min(delay_seconds, 3600))
        delivery.provider_response = send_result.response if send_result else {}
        delivery.last_error = send_result.error if send_result else "unsupported_channel"
        delivery.status = "dead_letter" if delivery.retries >= self.settings.notification_max_retries else "retry_scheduled"
        return {
            "id": delivery.id,
            "channel": delivery.channel,
            "sent": False,
            "status": delivery.status,
            "error": delivery.last_error,
        }

    def register_device_token(self, db: Session, *, user_id: str, platform: str, token: str) -> DeviceToken:
        existing = db.scalar(select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.token == token))
        now = datetime.now(timezone.utc)
        if existing:
            existing.platform = platform
            existing.status = "active"
            existing.last_seen_at = now
            db.commit()
            db.refresh(existing)
            return existing

        row = DeviceToken(
            user_id=user_id,
            platform=platform,
            token=token,
            status="active",
            last_seen_at=now,
        )
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

    def list_manager_notifications(self, db: Session, *, manager_id: str, limit: int = 100) -> list[NotificationDelivery]:
        return db.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.manager_id == manager_id)
            .order_by(NotificationDelivery.created_at.desc())
            .limit(limit)
        ).all()
