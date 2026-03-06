from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionTurn
from app.models.user import User
from app.schemas.manager_ai import (
    RepInsightContent,
    RepInsightResponse,
    SessionAnnotation,
    SessionAnnotationsResponse,
    TeamCoachingSummaryContent,
    TeamCoachingSummaryResponse,
)
from app.services.management_cache_service import ManagementCacheService

RUBRIC_CATEGORY_KEYS = {
    "opening": "opening",
    "pitch": "pitch",
    "pitch_delivery": "pitch",
    "objection_handling": "objection_handling",
    "closing": "closing",
    "closing_technique": "closing",
    "professionalism": "professionalism",
}


class AiCoachingUnavailableError(RuntimeError):
    pass


class AiCoachingDataUnavailableError(ValueError):
    pass


def _score_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        raw = value.get("score")
        if isinstance(raw, (int, float)):
            return float(raw)
    return None


def _linear_regression_slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    midpoint = (len(values) - 1) / 2
    average = sum(values) / len(values)
    numerator = sum((index - midpoint) * (value - average) for index, value in enumerate(values))
    denominator = sum((index - midpoint) ** 2 for index in range(len(values)))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _extract_json_block(raw_text: str) -> Any:
    text = raw_text.strip()
    if not text:
        raise AiCoachingUnavailableError("Claude returned an empty response")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for opening, closing in (("{", "}"), ("[", "]")):
        start = text.find(opening)
        end = text.rfind(closing)
        if start == -1 or end == -1 or end <= start:
            continue
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise AiCoachingUnavailableError("Claude returned invalid JSON")


def _extract_text_content(payload: dict[str, Any]) -> str:
    content = payload.get("content", [])
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[^.!?]+[.!?]", text.strip()))


def _trim_to_three_sentences(text: str) -> str:
    sentences = re.findall(r"[^.!?]+[.!?]", text.strip())
    if len(sentences) >= 3:
        return " ".join(sentence.strip() for sentence in sentences[:3]).strip()
    return text.strip()


class ManagerAiCoachingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        cache_size = max(128, self.settings.management_analytics_cache_max_entries)
        self.rep_insight_cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=3600,
            max_entries=cache_size,
        )
        self.session_annotations_cache = ManagementCacheService(
            redis_url=self.settings.redis_url,
            ttl_seconds=4 * 3600,
            max_entries=cache_size,
        )

    def generate_rep_insight(self, db: Session, *, rep: User, period_days: int) -> RepInsightResponse:
        cache_key = f"rep_insight:{rep.id}:{period_days}"
        cached = self.rep_insight_cache.get_json(cache_key)
        if cached is not None:
            return RepInsightResponse.model_validate(cached)

        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
        rows = db.execute(
            select(
                DrillSession.id.label("session_id"),
                DrillSession.started_at.label("started_at"),
                Scorecard.overall_score.label("overall_score"),
                Scorecard.category_scores.label("category_scores"),
                Scorecard.weakness_tags.label("weakness_tags"),
                Scorecard.highlights.label("highlights"),
                Scorecard.ai_summary.label("ai_summary"),
                Scenario.name.label("scenario_name"),
                Scenario.difficulty.label("scenario_difficulty"),
            )
            .join(Scorecard, Scorecard.session_id == DrillSession.id)
            .join(Scenario, Scenario.id == DrillSession.scenario_id)
            .where(DrillSession.rep_id == rep.id, DrillSession.started_at >= cutoff)
            .order_by(DrillSession.started_at.desc())
            .limit(30)
        ).mappings().all()

        if not rows:
            raise AiCoachingDataUnavailableError("No scored sessions are available for this rep in the selected period")

        scores = [float(row["overall_score"]) for row in rows if row["overall_score"] is not None]
        average_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        category_samples: dict[str, list[float]] = defaultdict(list)
        weakness_counts: Counter[str] = Counter()
        recent_summaries: list[dict[str, Any]] = []
        scenario_samples: list[dict[str, Any]] = []

        for row in rows:
            category_scores = row["category_scores"] or {}
            for raw_key, normalized_key in RUBRIC_CATEGORY_KEYS.items():
                value = _score_value(category_scores.get(raw_key))
                if value is not None:
                    category_samples[normalized_key].append(value)
            weakness_counts.update(tag for tag in (row["weakness_tags"] or []) if isinstance(tag, str) and tag.strip())
            recent_summaries.append(
                {
                    "session_id": row["session_id"],
                    "scenario_name": row["scenario_name"],
                    "scenario_difficulty": row["scenario_difficulty"],
                    "summary": row["ai_summary"],
                }
            )
            scenario_samples.append(
                {
                    "session_id": row["session_id"],
                    "scenario_name": row["scenario_name"],
                    "scenario_difficulty": row["scenario_difficulty"],
                    "overall_score": row["overall_score"],
                }
            )

        category_averages = {
            "opening": round(sum(category_samples.get("opening", [])) / max(len(category_samples.get("opening", [])), 1), 2)
            if category_samples.get("opening")
            else 0.0,
            "pitch": round(sum(category_samples.get("pitch", [])) / max(len(category_samples.get("pitch", [])), 1), 2)
            if category_samples.get("pitch")
            else 0.0,
            "objection_handling": round(
                sum(category_samples.get("objection_handling", [])) / max(len(category_samples.get("objection_handling", [])), 1),
                2,
            )
            if category_samples.get("objection_handling")
            else 0.0,
            "closing": round(sum(category_samples.get("closing", [])) / max(len(category_samples.get("closing", [])), 1), 2)
            if category_samples.get("closing")
            else 0.0,
            "professionalism": round(
                sum(category_samples.get("professionalism", [])) / max(len(category_samples.get("professionalism", [])), 1),
                2,
            )
            if category_samples.get("professionalism")
            else 0.0,
        }

        trend_rows = list(reversed(rows[:10]))
        trend_scores = [float(row["overall_score"]) for row in trend_rows if row["overall_score"] is not None]
        trend_slope = round(_linear_regression_slope(trend_scores), 3)
        trend_delta = round((trend_scores[-1] - trend_scores[0]) if len(trend_scores) >= 2 else 0.0, 2)
        if trend_delta > 0.25:
            trend_direction = "improving"
        elif trend_delta < -0.25:
            trend_direction = "declining"
        else:
            trend_direction = "flat"

        top_weakness_tags = [tag for tag, _ in weakness_counts.most_common(3)]
        below_threshold_count = sum(1 for score in scores if score < 6.0)
        last_three_summaries = "\n".join(
            f"- {item['scenario_name']} (difficulty {item['scenario_difficulty']}): {item['summary']}"
            for item in recent_summaries[:3]
        ) or "- No recent AI summaries available."

        prompt = f"""
You are an expert D2D sales coach analyzing a rep's training data.

Rep data:
- Name: {rep.name}
- Sessions analyzed: {len(rows)}
- Average score: {average_score}/10
- Score trend: {trend_direction} ({trend_delta:+.1f} over last 10 sessions)
- Category averages: Opening {category_averages['opening']}/10, Pitch {category_averages['pitch']}/10, Objection Handling {category_averages['objection_handling']}/10, Closing {category_averages['closing']}/10, Professionalism {category_averages['professionalism']}/10
- Top weakness tags: {", ".join(top_weakness_tags) if top_weakness_tags else "None identified"}
- Recent AI session summaries:
{last_three_summaries}

Provide a coaching analysis in this exact JSON format:
{{
  "headline": "one sentence diagnosis (max 15 words)",
  "primary_weakness": "the single most important area to fix",
  "root_cause": "why this weakness likely exists (2 sentences)",
  "drill_recommendation": "specific scenario type and difficulty to assign next",
  "coaching_script": "3-4 sentences the manager should say directly to this rep",
  "expected_improvement": "what should improve and in how many sessions if coaching works"
}}
""".strip()

        content = RepInsightContent.model_validate(
            self._call_claude_json(
                system_prompt="You are a precise sales coaching analyst. Return only valid JSON.",
                user_prompt=prompt,
                max_tokens=700,
            )
        )

        data_summary = {
            "period_days": period_days,
            "session_count": len(rows),
            "average_score": average_score,
            "category_averages": category_averages,
            "top_weakness_tags": top_weakness_tags,
            "below_six_count": below_threshold_count,
            "trend": {
                "direction": trend_direction,
                "delta": trend_delta,
                "slope": trend_slope,
                "session_count": len(trend_scores),
            },
            "recent_session_summaries": recent_summaries[:3],
            "recent_scenarios": scenario_samples[:10],
        }
        response = RepInsightResponse(
            rep_id=rep.id,
            rep_name=rep.name,
            generated_at=datetime.now(timezone.utc).isoformat(),
            data_summary=data_summary,
            **content.model_dump(),
        )
        self.rep_insight_cache.set_json(cache_key, response.model_dump(mode="json"))
        return response

    def generate_session_annotations(self, db: Session, *, session_id: str) -> SessionAnnotationsResponse:
        cache_key = f"session_annotations:{session_id}"
        cached = self.session_annotations_cache.get_json(cache_key)
        if cached is not None:
            return SessionAnnotationsResponse.model_validate(cached)

        turns = db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())
        ).all()
        if not turns:
            raise AiCoachingDataUnavailableError("Transcript turns are not available for this session")

        scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
        if scorecard is None:
            raise AiCoachingDataUnavailableError("Scorecard is not available for this session")

        transcript = "\n".join(
            f'[TURN {turn.turn_index} | TURN_ID {turn.id}] {turn.speaker.value.upper()}: "{turn.text}"'
            for turn in turns
        )
        highlights = []
        for item in scorecard.highlights or []:
            if not isinstance(item, dict):
                continue
            note = item.get("note")
            highlight_type = item.get("type")
            if isinstance(note, str) and note.strip():
                highlights.append(f"- {highlight_type or 'note'}: {note}")
        prompt = f"""
You are a D2D sales training coach. Analyze this sales call transcript and identify the 3-5 most instructive moments - moments where the rep either did something particularly well or made a mistake that should be discussed in coaching.

Transcript:
{transcript}

Scorecard context:
- Overall score: {scorecard.overall_score}/10
- Weakness tags: {", ".join(scorecard.weakness_tags) if scorecard.weakness_tags else "None"}
- Highlights:
{chr(10).join(highlights) if highlights else "- None"}

Return JSON array:
[
  {{
    "turn_id": "the turn_id of the moment",
    "type": "strength" | "weakness",
    "label": "short label (max 6 words)",
    "explanation": "what the rep did and why it matters (2-3 sentences)",
    "coaching_tip": "what the rep should have said or done instead (1-2 sentences, only for weakness type)"
  }}
]
""".strip()

        raw_items = self._call_claude_json(
            system_prompt="You are a precise transcript coach. Return only valid JSON.",
            user_prompt=prompt,
            max_tokens=1000,
        )
        if not isinstance(raw_items, list):
            raise AiCoachingUnavailableError("Claude returned an invalid annotations payload")

        turn_index_by_id = {turn.id: turn.turn_index for turn in turns}
        seen_turn_ids: set[str] = set()
        annotations: list[SessionAnnotation] = []
        for item in raw_items:
            annotation = SessionAnnotation.model_validate(item)
            if annotation.turn_id not in turn_index_by_id or annotation.turn_id in seen_turn_ids:
                continue
            seen_turn_ids.add(annotation.turn_id)
            annotations.append(annotation)

        annotations.sort(key=lambda item: turn_index_by_id[item.turn_id])
        response = SessionAnnotationsResponse(
            session_id=session_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            annotations=annotations,
        )
        self.session_annotations_cache.set_json(cache_key, response.model_dump(mode="json"))
        return response

    def generate_team_coaching_summary(
        self,
        *,
        manager: User,
        period_days: int,
        coaching_analytics: dict[str, Any],
    ) -> TeamCoachingSummaryResponse:
        summary = coaching_analytics.get("summary", {}) if isinstance(coaching_analytics, dict) else {}
        weakness_items = coaching_analytics.get("weakness_tag_uplift", []) if isinstance(coaching_analytics, dict) else []
        uplift_items = coaching_analytics.get("coaching_uplift", []) if isinstance(coaching_analytics, dict) else []
        calibration_items = coaching_analytics.get("manager_calibration", []) if isinstance(coaching_analytics, dict) else []
        recent_notes = coaching_analytics.get("recent_notes", []) if isinstance(coaching_analytics, dict) else []
        retry_items = coaching_analytics.get("retry_impact", []) if isinstance(coaching_analytics, dict) else []

        top_weaknesses = [
            {
                "tag": item.get("tag"),
                "delta": item.get("delta"),
                "sample_size": item.get("sample_size"),
            }
            for item in weakness_items[:4]
            if isinstance(item, dict)
        ]
        top_uplifts = [
            {
                "rep_name": item.get("rep_name"),
                "delta": item.get("delta"),
                "outcome": item.get("outcome"),
                "visible_to_rep": item.get("visible_to_rep"),
            }
            for item in uplift_items[:3]
            if isinstance(item, dict)
        ]
        highest_drift = sorted(
            [
                {
                    "reviewer_name": item.get("reviewer_name"),
                    "average_override_delta": item.get("average_override_delta"),
                    "absolute_average_delta": item.get("absolute_average_delta"),
                }
                for item in calibration_items
                if isinstance(item, dict)
            ],
            key=lambda item: abs(float(item.get("absolute_average_delta") or 0.0)),
            reverse=True,
        )[:2]
        recent_note_previews = [
            {
                "rep_name": item.get("rep_name"),
                "weakness_tags": item.get("weakness_tags"),
                "note": item.get("note"),
                "delta": item.get("delta"),
            }
            for item in recent_notes[:3]
            if isinstance(item, dict)
        ]

        prompt = f"""
You are an expert D2D sales coaching strategist summarizing a manager's coaching patterns.

Manager data:
- Manager: {manager.name}
- Period: {period_days} days
- Coaching notes: {summary.get('coaching_note_count', 0)}
- Reviews: {summary.get('review_count', 0)}
- Override rate: {round(float(summary.get('override_rate', 0.0)) * 100, 1)}%
- Avg override delta: {summary.get('average_override_delta')}
- Retry uplift avg: {summary.get('retry_uplift_avg')}
- Coached retry uplift avg: {summary.get('coached_retry_uplift_avg')}
- Intervention improved rate: {summary.get('intervention_improved_rate')}
- Calibration drift score: {summary.get('calibration_drift_score')}
- Top weakness trends: {json.dumps(top_weaknesses, default=str)}
- Strongest coaching uplifts: {json.dumps(top_uplifts, default=str)}
- Highest calibration drift: {json.dumps(highest_drift, default=str)}
- Recent coaching notes: {json.dumps(recent_note_previews, default=str)}
- Retry samples: {json.dumps(retry_items[:3], default=str)}

Return JSON:
{{
  "summary": "Exactly 3 sentences. Be specific, managerial, and action-oriented."
}}
""".strip()

        content = TeamCoachingSummaryContent.model_validate(
            self._call_claude_json(
                system_prompt="You are a precise coaching strategist. Return only valid JSON.",
                user_prompt=prompt,
                max_tokens=320,
            )
        )
        summary_text = _trim_to_three_sentences(content.summary)
        if _sentence_count(summary_text) > 3:
            summary_text = _trim_to_three_sentences(summary_text)

        data_summary = {
            "period_days": period_days,
            "summary": summary,
            "top_weakness_trends": top_weaknesses,
            "strongest_uplifts": top_uplifts,
            "highest_calibration_drift": highest_drift,
            "recent_note_previews": recent_note_previews,
        }
        return TeamCoachingSummaryResponse(
            manager_id=manager.id,
            period_days=period_days,
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary=summary_text,
            data_summary=data_summary,
        )

    def _call_claude_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> Any:
        if not self.settings.anthropic_api_key:
            raise AiCoachingUnavailableError("Claude analysis is unavailable because Anthropic is not configured")

        try:
            with httpx.Client(timeout=self.settings.provider_timeout_seconds) as client:
                response = client.post(
                    f"{self.settings.anthropic_base_url.rstrip('/')}/v1/messages",
                    headers={
                        "x-api-key": self.settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.settings.anthropic_model,
                        "max_tokens": max_tokens,
                        "temperature": 0.2,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AiCoachingUnavailableError("Claude analysis is temporarily unavailable") from exc

        content = _extract_text_content(response.json())
        return _extract_json_block(content)
