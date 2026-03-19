from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.org_prompt_config import OrgPromptConfig
from app.models.prompt_version import PromptVersion
from app.services.conversation_orchestrator import PromptBuilder, measure_prompt_tokens
from app.services.grading_service import GradingPromptBuilder
from app.services.org_prompt_rendering import build_company_context_layer, summarize_target_demographics

COACHING_BASE_PROMPT = (
    "You are a seasoned door-to-door sales manager preparing coaching feedback for your team. "
    "Be direct, evidence-based, and rep-focused. "
    "When identifying weaknesses, always cite a specific transcript moment. "
    "Avoid generic praise. Prioritize objection handling and close technique gaps."
)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


class PromptVersionSynthesizer:
    def __init__(self) -> None:
        self.environment = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def synthesize_for_org(self, config: OrgPromptConfig, db: Session) -> dict[str, PromptVersion]:
        rendered = self.render_for_org(config)
        version = datetime.now(timezone.utc).strftime("org_%Y%m%d%H%M%S%f")
        created: dict[str, PromptVersion] = {}

        rows_to_persist = (
            ("conversation", "conversation", rendered["conversation"]),
            ("grading", "grading_v2", rendered["grading"]),
            ("coaching", "coaching", rendered["coaching"]),
        )
        for response_key, prompt_type, content in rows_to_persist:
            for sibling in db.scalars(
                select(PromptVersion)
                .where(PromptVersion.prompt_type == prompt_type)
                .where(PromptVersion.org_id == config.org_id)
            ).all():
                sibling.active = False

            row = PromptVersion(
                prompt_type=prompt_type,
                version=version,
                org_id=config.org_id,
                content=content,
                active=True,
            )
            db.add(row)
            db.flush()
            created[response_key] = row

        return created

    def render_for_org(self, config: OrgPromptConfig) -> dict[str, str]:
        context = self._template_context(config)
        rendered = {
            "conversation": self.environment.get_template("conversation_base.j2").render(**context).strip(),
            "grading": self.environment.get_template("grading_base.j2").render(**context).strip(),
            "coaching": self.environment.get_template("coaching_base.j2").render(**context).strip(),
        }
        return {
            key: self._normalize_rendered_prompt(value)
            for key, value in rendered.items()
        }

    def build_preview(self, config: OrgPromptConfig) -> dict[str, Any]:
        rendered = self.render_for_org(config)
        layer_zero = build_company_context_layer(config, require_published=False)
        conversation_preview = "\n\n".join(
            part for part in (layer_zero, rendered["conversation"]) if part
        )
        return {
            "org_id": config.org_id,
            "published": bool(config.published),
            "layer_0_preview": layer_zero,
            "conversation_prompt": conversation_preview,
            "grading_prompt": rendered["grading"],
            "coaching_prompt": rendered["coaching"],
            "system_prompt_token_count": measure_prompt_tokens(conversation_preview),
        }

    def _template_context(self, config: OrgPromptConfig) -> dict[str, Any]:
        return {
            "company_name": config.company_name or "Company",
            "product_category": config.product_category or "product",
            "product_description": (config.product_description or "").strip(),
            "pitch_stages": self._clean_string_list(config.pitch_stages),
            "unique_selling_points": self._clean_string_list(config.unique_selling_points),
            "known_objections": self._normalize_objections(config.known_objections),
            "target_demographics": dict(config.target_demographics or {}),
            "target_demographics_items": list(self._normalize_target_demographics(config.target_demographics).items()),
            "target_demographics_summary": summarize_target_demographics(config.target_demographics),
            "competitors": self._normalize_competitors(config.competitors),
            "pricing_framing": (config.pricing_framing or "").strip(),
            "close_style": (config.close_style or "").strip(),
            "rep_tone_guidance": (config.rep_tone_guidance or "").strip(),
            "grading_priorities": self._clean_string_list(config.grading_priorities),
            "company_context_layer": build_company_context_layer(config, require_published=False) or "",
            "conversation_base_blueprint": PromptBuilder.template_blueprint(),
            "grading_base_blueprint": GradingPromptBuilder.template_blueprint(),
            "coaching_base_prompt": COACHING_BASE_PROMPT,
        }

    def _normalize_objections(self, raw_value: Any) -> list[dict[str, str]]:
        objections: list[dict[str, str]] = []
        if not isinstance(raw_value, list):
            return objections
        for item in raw_value:
            if isinstance(item, dict):
                objection = str(item.get("objection") or "").strip()
                rebuttal = str(item.get("preferred_rebuttal_hint") or "").strip()
            else:
                objection = str(item or "").strip()
                rebuttal = ""
            if not objection:
                continue
            objections.append(
                {
                    "objection": objection,
                    "preferred_rebuttal_hint": rebuttal,
                }
            )
        return objections

    def _normalize_competitors(self, raw_value: Any) -> list[dict[str, str]]:
        competitors: list[dict[str, str]] = []
        if not isinstance(raw_value, list):
            return competitors
        for item in raw_value:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                differentiator = str(item.get("key_differentiator") or "").strip()
            else:
                name = str(item or "").strip()
                differentiator = ""
            if not name:
                continue
            competitors.append(
                {
                    "name": name,
                    "key_differentiator": differentiator,
                }
            )
        return competitors

    def _normalize_target_demographics(self, raw_value: Any) -> dict[str, str]:
        if not isinstance(raw_value, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, value in raw_value.items():
            if isinstance(value, list):
                value_text = ", ".join(
                    str(item).strip() for item in value if str(item).strip()
                )
            else:
                value_text = str(value or "").strip()
            if not value_text:
                continue
            normalized[key.replace("_", " ").title()] = value_text
        return normalized

    def _clean_string_list(self, raw_value: Any) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        return [str(item).strip() for item in raw_value if str(item).strip()]

    def _normalize_rendered_prompt(self, value: str) -> str:
        lines = [line.rstrip() for line in value.splitlines()]
        normalized: list[str] = []
        previous_blank = False
        for line in lines:
            is_blank = not line.strip()
            if is_blank and previous_blank:
                continue
            normalized.append(line)
            previous_blank = is_blank
        return "\n".join(normalized).strip()
