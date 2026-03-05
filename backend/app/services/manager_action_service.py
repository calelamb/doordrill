from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.manager_action import ManagerActionLog


class ManagerActionService:
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

    def recent(self, db: Session, *, manager_id: str, limit: int = 50) -> list[ManagerActionLog]:
        limit = max(1, min(limit, 200))
        stmt = (
            select(ManagerActionLog)
            .where(ManagerActionLog.manager_id == manager_id)
            .order_by(ManagerActionLog.occurred_at.desc())
            .limit(limit)
        )
        return db.scalars(stmt).all()
