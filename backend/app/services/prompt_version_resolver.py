from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prompt_version import PromptVersion
from app.models.session import Session as DrillSession
from app.services.prompt_experiment_service import PromptExperimentService

DEFAULT_COACHING_PROMPT_CONTENT = (
    "You are a seasoned door-to-door sales manager preparing coaching feedback for your team. "
    "Be direct, evidence-based, and rep-focused."
)


class PromptVersionResolver:
    def __init__(self) -> None:
        self.prompt_experiment_service = PromptExperimentService()
        self._session_cache: dict[tuple[str, str | None, str], str] = {}

    def resolve(
        self,
        prompt_type: str,
        org_id: str | None,
        session_id: str,
        db: Session,
    ) -> PromptVersion:
        cache_key = (prompt_type, org_id, session_id)
        cached_id = self._session_cache.get(cache_key)
        if cached_id is not None:
            cached = db.get(PromptVersion, cached_id)
            if cached is not None:
                return cached
            self._session_cache.pop(cache_key, None)

        locked_version = self._resolve_locked_conversation_prompt(
            prompt_type=prompt_type,
            org_id=org_id,
            session_id=session_id,
            db=db,
        )
        if locked_version is not None:
            self._session_cache[cache_key] = locked_version.id
            return locked_version

        experiment = self.prompt_experiment_service.get_active_experiment(
            db,
            prompt_type=prompt_type,
            org_id=org_id,
        )
        if experiment is not None:
            selected = self._select_experiment_version(
                experiment=experiment,
                prompt_type=prompt_type,
                org_id=org_id,
                session_id=session_id,
                db=db,
            )
            if selected is not None:
                self._session_cache[cache_key] = selected.id
                return selected

        scoped_active = self._get_active_prompt_version(
            db,
            prompt_type=prompt_type,
            org_id=org_id,
        )
        if scoped_active is not None:
            self._session_cache[cache_key] = scoped_active.id
            return scoped_active

        if org_id is not None:
            global_active = self._get_active_prompt_version(
                db,
                prompt_type=prompt_type,
                org_id=None,
            )
            if global_active is not None:
                self._session_cache[cache_key] = global_active.id
                return global_active

        seeded = self._ensure_active_prompt_version(prompt_type=prompt_type, db=db)
        self._session_cache[cache_key] = seeded.id
        return seeded

    def invalidate(self, *, prompt_type: str | None = None, org_id: str | None | object = None) -> None:
        remaining: dict[tuple[str, str | None, str], str] = {}
        for key, value in self._session_cache.items():
            key_prompt_type, key_org_id, _ = key
            if prompt_type is not None and key_prompt_type != prompt_type:
                remaining[key] = value
                continue
            if org_id is not None and key_org_id != org_id:
                remaining[key] = value
                continue
        self._session_cache = remaining

    def _resolve_locked_conversation_prompt(
        self,
        *,
        prompt_type: str,
        org_id: str | None,
        session_id: str,
        db: Session,
    ) -> PromptVersion | None:
        if prompt_type != "conversation" or not session_id:
            return None

        session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
        if session is None or not session.prompt_version:
            return None

        scoped_stmt = (
            select(PromptVersion)
            .where(PromptVersion.prompt_type == prompt_type)
            .where(PromptVersion.version == session.prompt_version)
            .order_by(PromptVersion.active.desc(), PromptVersion.created_at.desc())
        )
        if org_id is not None:
            scoped_row = db.scalar(scoped_stmt.where(PromptVersion.org_id == org_id))
            if scoped_row is not None:
                return scoped_row

        return db.scalar(scoped_stmt.where(PromptVersion.org_id.is_(None)))

    def _select_experiment_version(
        self,
        *,
        experiment: Any,
        prompt_type: str,
        org_id: str | None,
        session_id: str,
        db: Session,
    ) -> PromptVersion | None:
        bucket = int(hashlib.md5(session_id.encode("utf-8")).hexdigest(), 16) % 100
        selected_id = (
            experiment.challenger_version_id
            if bucket < int(experiment.challenger_traffic_pct)
            else experiment.control_version_id
        )
        selected = db.get(PromptVersion, selected_id)
        if selected is None or selected.prompt_type != prompt_type:
            return None
        if selected.org_id == org_id:
            return selected
        if selected.org_id is None:
            return selected
        return None

    def _get_active_prompt_version(
        self,
        db: Session,
        *,
        prompt_type: str,
        org_id: str | None,
    ) -> PromptVersion | None:
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.prompt_type == prompt_type)
            .where(PromptVersion.active.is_(True))
            .order_by(PromptVersion.created_at.desc())
        )
        if org_id is None:
            stmt = stmt.where(PromptVersion.org_id.is_(None))
        else:
            stmt = stmt.where(PromptVersion.org_id == org_id)
        return db.scalar(stmt)

    def _ensure_active_prompt_version(self, *, prompt_type: str, db: Session) -> PromptVersion:
        row = self._get_active_prompt_version(db, prompt_type=prompt_type, org_id=None)
        if row is not None:
            return row

        version = self._default_version_for(prompt_type)
        content = self._default_content_for(prompt_type)

        row = db.scalar(
            select(PromptVersion)
            .where(PromptVersion.prompt_type == prompt_type)
            .where(PromptVersion.version == version)
            .where(PromptVersion.org_id.is_(None))
        )
        if row is None:
            row = PromptVersion(
                prompt_type=prompt_type,
                version=version,
                org_id=None,
                content=content,
                active=True,
            )
            db.add(row)
            db.flush()
        else:
            row.content = content
            row.active = True

        for existing in db.scalars(
            select(PromptVersion)
            .where(PromptVersion.prompt_type == prompt_type)
            .where(PromptVersion.org_id.is_(None))
        ).all():
            existing.active = existing.id == row.id
        db.flush()
        return row

    def _default_version_for(self, prompt_type: str) -> str:
        if prompt_type == "conversation":
            return "conversation_v1"
        if prompt_type == "coaching":
            return "coaching_v1"
        if prompt_type == "grading":
            return "grading_v1"
        if prompt_type == "grading_v2":
            return "1.0.0"
        return "default_v1"

    def _default_content_for(self, prompt_type: str) -> str:
        if prompt_type == "conversation":
            from app.services.conversation_orchestrator import PromptBuilder

            return PromptBuilder.template_blueprint()
        if prompt_type in {"grading", "grading_v2"}:
            from app.services.grading_service import GradingPromptBuilder

            return GradingPromptBuilder.template_blueprint()
        if prompt_type == "coaching":
            return DEFAULT_COACHING_PROMPT_CONTENT
        raise ValueError(f"unsupported prompt_type: {prompt_type}")


prompt_version_resolver = PromptVersionResolver()
