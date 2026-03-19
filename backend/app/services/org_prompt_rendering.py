from __future__ import annotations

from typing import Any

from app.models.org_prompt_config import OrgPromptConfig


def summarize_target_demographics(target_demographics: dict[str, Any] | None) -> str:
    if not isinstance(target_demographics, dict) or not target_demographics:
        return "broad homeowner audience"

    parts: list[str] = []
    age_range = _string_value(target_demographics.get("age_range"))
    if age_range:
        parts.append(f"age {age_range}")

    homeowner_type = _string_value(target_demographics.get("homeowner_type"))
    if homeowner_type:
        parts.append(homeowner_type)

    income_bracket = _string_value(target_demographics.get("income_bracket"))
    if income_bracket:
        parts.append(f"income {income_bracket}")

    common_concerns = _string_list(target_demographics.get("common_concerns"))
    if common_concerns:
        parts.append(f"concerns: {', '.join(common_concerns[:3])}")

    for key, value in target_demographics.items():
        if key in {"age_range", "homeowner_type", "income_bracket", "common_concerns"}:
            continue
        normalized = _string_value(value)
        if not normalized:
            continue
        parts.append(f"{key.replace('_', ' ')}: {normalized}")

    summary = "; ".join(parts)
    return summary[:220] if summary else "broad homeowner audience"


def build_company_context_layer(
    config: OrgPromptConfig | None,
    *,
    require_published: bool = True,
) -> str | None:
    if config is None:
        return None
    if require_published and not bool(config.published):
        return None

    company_name = _string_value(config.company_name) or "the company"
    product_category = _string_value(config.product_category) or "their product"
    product_description = _single_line(config.product_description) or "No detailed product description provided."
    target_summary = summarize_target_demographics(config.target_demographics)
    close_style = _string_value(config.close_style) or "consultative"

    return (
        "=== COMPANY CONTEXT ===\n"
        f"You are roleplaying as a homeowner being approached by a rep from {company_name}.\n"
        f"They sell {product_category}: {product_description}\n"
        f"Target customer profile: {target_summary}\n"
        f"Close style expected from rep: {close_style}"
    )


def _single_line(value: Any) -> str:
    return " ".join(str(value or "").split())[:220]


def _string_value(value: Any) -> str:
    return str(value or "").strip()[:120]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
