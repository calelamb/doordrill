from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.org_prompt_config import OrgPromptConfig
from app.services.prompt_version_resolver import prompt_version_resolver

ORG_PROMPT_CONFIG_FIELDS = (
    "id",
    "org_id",
    "company_name",
    "product_category",
    "product_description",
    "pitch_stages",
    "unique_selling_points",
    "known_objections",
    "target_demographics",
    "competitors",
    "pricing_framing",
    "close_style",
    "rep_tone_guidance",
    "grading_priorities",
    "published",
    "created_at",
    "updated_at",
)

ORG_PROMPT_CONFIG_UPDATABLE_FIELDS = {
    "company_name",
    "product_category",
    "product_description",
    "pitch_stages",
    "unique_selling_points",
    "known_objections",
    "target_demographics",
    "competitors",
    "pricing_framing",
    "close_style",
    "rep_tone_guidance",
    "grading_priorities",
}


class OrgPromptConfigService:
    _active_config_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=256, ttl=300)

    def get_config(self, org_id: str, db: Session) -> OrgPromptConfig | None:
        if not org_id:
            return None
        return db.scalar(
            select(OrgPromptConfig)
            .where(OrgPromptConfig.org_id == org_id)
            .where(OrgPromptConfig.published.is_(True))
        )

    def get_or_create_draft(self, org_id: str, db: Session) -> OrgPromptConfig:
        config = db.scalar(select(OrgPromptConfig).where(OrgPromptConfig.org_id == org_id))
        if config is not None:
            return config

        config = OrgPromptConfig(
            org_id=org_id,
            company_name="",
            product_category="",
            product_description=None,
            pitch_stages=[],
            unique_selling_points=[],
            known_objections=[],
            target_demographics={},
            competitors=[],
            pricing_framing=None,
            close_style=None,
            rep_tone_guidance=None,
            grading_priorities=[],
            published=False,
        )
        db.add(config)
        db.flush()
        self._invalidate_active_cache(org_id)
        return config

    def update_config(self, org_id: str, updates: dict, db: Session) -> OrgPromptConfig:
        config = self.get_or_create_draft(org_id, db)
        now = datetime.now(timezone.utc)

        for field, value in updates.items():
            if field not in ORG_PROMPT_CONFIG_UPDATABLE_FIELDS:
                raise ValueError(f"unsupported org prompt config field: {field}")
            current_value = getattr(config, field)
            if isinstance(current_value, dict) and isinstance(value, dict):
                merged = dict(current_value)
                merged.update(copy.deepcopy(value))
                setattr(config, field, merged)
                continue
            setattr(config, field, copy.deepcopy(value))

        config.updated_at = now
        db.flush()
        self._invalidate_active_cache(org_id)
        return config

    def publish_config(self, org_id: str, db: Session) -> OrgPromptConfig:
        from app.services.prompt_version_synthesizer import PromptVersionSynthesizer

        config = self.get_or_create_draft(org_id, db)
        config.published = True
        config.updated_at = datetime.now(timezone.utc)
        db.flush()

        PromptVersionSynthesizer().synthesize_for_org(config, db)
        prompt_version_resolver.invalidate(org_id=org_id)
        self._cache_active_config(config)
        return config

    def get_active_config(self, org_id: str, db: Session) -> OrgPromptConfig | None:
        if not org_id:
            return None

        cache_key = str(org_id)
        cached = self._active_config_cache.get(cache_key, ...)
        if cached is not ...:
            return None if cached is None else self._hydrate_cached_config(cached)

        config = self.get_config(org_id, db)
        if config is None:
            self._active_config_cache[cache_key] = None
            return None

        self._cache_active_config(config)
        return self._hydrate_cached_config(self._active_config_cache[cache_key] or {})

    def _cache_active_config(self, config: OrgPromptConfig) -> None:
        self._active_config_cache[str(config.org_id)] = self._serialize_config(config)

    def _invalidate_active_cache(self, org_id: str) -> None:
        self._active_config_cache.pop(str(org_id), None)

    def invalidate_cache(self, org_id: str) -> None:
        self._invalidate_active_cache(org_id)

    def _serialize_config(self, config: OrgPromptConfig) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field in ORG_PROMPT_CONFIG_FIELDS:
            payload[field] = copy.deepcopy(getattr(config, field))
        return payload

    def _hydrate_cached_config(self, payload: dict[str, Any]) -> OrgPromptConfig:
        return OrgPromptConfig(**copy.deepcopy(payload))
