from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.assignment import Assignment
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession

SKILL_ORDER = ["opening", "rapport", "pitch_clarity", "objection_handling", "closing"]
SKILL_GRAPH_EDGES = [
    {
        "from_skill": "opening",
        "to_skill": "rapport",
        "weight": 0.35,
        "rationale": "A stronger opener gives the homeowner a reason to stay in the conversation.",
    },
    {
        "from_skill": "rapport",
        "to_skill": "pitch_clarity",
        "weight": 0.2,
        "rationale": "Trust makes the core pitch easier to hear and process.",
    },
    {
        "from_skill": "pitch_clarity",
        "to_skill": "objection_handling",
        "weight": 0.3,
        "rationale": "Clear value statements reduce confusion when objections arrive.",
    },
    {
        "from_skill": "objection_handling",
        "to_skill": "closing",
        "weight": 0.35,
        "rationale": "Reps who resolve objections cleanly earn the right to ask for the next step.",
    },
    {
        "from_skill": "rapport",
        "to_skill": "closing",
        "weight": 0.15,
        "rationale": "Homeowners are more willing to advance when the interaction feels respectful.",
    },
]
EMOTION_RESISTANCE = {"interested": 1, "curious": 2, "neutral": 3, "skeptical": 4, "annoyed": 5, "hostile": 5}
ATTITUDE_RESISTANCE = {"friendly": 1, "interested": 2, "curious": 2, "neutral": 3, "skeptical": 4, "busy": 4, "annoyed": 5, "hostile": 5}
ATTITUDE_PATIENCE = {"friendly": 5, "interested": 4, "curious": 4, "neutral": 3, "skeptical": 3, "busy": 2, "annoyed": 1, "hostile": 1}


class AdaptiveTrainingService:
    """Builds rep skill profiles and recommends scenario difficulty from historical session data."""

    def build_plan(self, db: Session, rep_id: str) -> dict[str, Any]:
        sessions = db.scalars(
            select(DrillSession)
            .where(DrillSession.rep_id == rep_id)
            .order_by(DrillSession.ended_at.asc(), DrillSession.created_at.asc())
            .options(selectinload(DrillSession.scorecard), selectinload(DrillSession.turns))
        ).all()
        scenario_ids = {session.scenario_id for session in sessions}
        scenarios = db.scalars(select(Scenario)).all()
        scenario_map = {scenario.id: scenario for scenario in scenarios}
        historical_scenarios = {scenario_id: scenario_map.get(scenario_id) for scenario_id in scenario_ids}

        snapshots = [
            self._build_session_snapshot(session=session, scenario=historical_scenarios.get(session.scenario_id))
            for session in sessions
            if session.scorecard is not None
        ]

        skill_profile = self._build_skill_profile(snapshots)
        performance_trend = self._compute_performance_trend(snapshots)
        recommended_difficulty = self._recommended_difficulty(skill_profile=skill_profile, performance_trend=performance_trend)
        target_difficulty_factors = self._target_difficulty_factors(
            skill_profile=skill_profile,
            recommended_difficulty=recommended_difficulty,
        )
        weakest_skills = [
            node["skill"]
            for node in sorted(skill_profile.values(), key=lambda item: (item["score"], item["skill"]))[:2]
        ]
        recommendations = self._recommend_scenarios(
            scenarios=scenarios,
            skill_profile=skill_profile,
            recommended_difficulty=recommended_difficulty,
            target_difficulty_factors=target_difficulty_factors,
            weakest_skills=weakest_skills,
        )

        return {
            "rep_id": rep_id,
            "session_count": len(snapshots),
            "readiness_score": round(self._mean(node["score"] for node in skill_profile.values()), 2),
            "performance_trend": performance_trend,
            "recommended_difficulty": recommended_difficulty,
            "weakest_skills": weakest_skills,
            "target_difficulty_factors": target_difficulty_factors,
            "skill_profile": [skill_profile[skill] for skill in SKILL_ORDER],
            "skill_graph": SKILL_GRAPH_EDGES,
            "recommended_scenarios": recommendations,
        }

    def create_adaptive_assignment(
        self,
        db: Session,
        *,
        rep_id: str,
        assigned_by: str,
        due_at: datetime | None,
        min_score_target: float | None,
        retry_policy: dict[str, Any] | None,
        scenario_id: str | None = None,
    ) -> dict[str, Any]:
        plan = self.build_plan(db, rep_id)
        recommendations = plan["recommended_scenarios"]
        if scenario_id:
            selected = next((item for item in recommendations if item["scenario_id"] == scenario_id), None)
            if selected is None:
                scenario = db.scalar(select(Scenario).where(Scenario.id == scenario_id))
                if scenario is None:
                    raise ValueError("scenario not found")
                selected = self._recommend_scenarios(
                    scenarios=[scenario],
                    skill_profile={node["skill"]: node for node in plan["skill_profile"]},
                    recommended_difficulty=plan["recommended_difficulty"],
                    target_difficulty_factors=plan["target_difficulty_factors"],
                    weakest_skills=plan["weakest_skills"],
                )[0]
        else:
            if not recommendations:
                raise ValueError("no scenarios available for recommendation")
            selected = recommendations[0]

        adaptive_metadata = {
            "source": "adaptive_training_engine",
            "recommended_difficulty": plan["recommended_difficulty"],
            "weakest_skills": plan["weakest_skills"],
            "target_difficulty_factors": plan["target_difficulty_factors"],
            "selected_scenario_id": selected["scenario_id"],
            "selected_scenario_score": selected["recommendation_score"],
        }
        assignment = Assignment(
            scenario_id=selected["scenario_id"],
            rep_id=rep_id,
            assigned_by=assigned_by,
            due_at=due_at,
            min_score_target=min_score_target if min_score_target is not None else self._default_target_score(plan["skill_profile"]),
            retry_policy={**(retry_policy or {}), "adaptive_training": adaptive_metadata},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return {"assignment": assignment, "adaptive_plan": plan, "selected_scenario": selected}

    def _build_session_snapshot(self, *, session: DrillSession, scenario: Scenario | None) -> dict[str, Any]:
        scorecard = session.scorecard
        if scorecard is None:
            return {}

        category_scores = scorecard.category_scores or {}
        opening = self._bounded_score(category_scores.get("opening"), fallback=5.0)
        professionalism = self._bounded_score(category_scores.get("professionalism"), fallback=6.0)
        pitch = self._bounded_score(category_scores.get("pitch_delivery"), fallback=5.0)
        objections = self._bounded_score(category_scores.get("objection_handling"), fallback=5.0)
        closing = self._bounded_score(category_scores.get("closing_technique"), fallback=5.0)

        emotion_start, emotion_end = self._extract_emotions(session)
        emotion_recovery = self._emotion_recovery_score(emotion_start, emotion_end)
        objection_load = len({tag for turn in session.turns for tag in (turn.objection_tags or [])}) or 1
        scenario_difficulty = max(1, min(5, int(scenario.difficulty if scenario else 1)))
        scenario_factors = self._scenario_difficulty_factors(scenario)
        challenge_bonus = max(0.0, (scenario_difficulty - 2) * 0.25)

        skills = {
            "opening": self._clamp_10(opening),
            "rapport": self._clamp_10((opening * 0.35) + (professionalism * 0.35) + (emotion_recovery * 0.3)),
            "pitch_clarity": self._clamp_10((pitch * 0.8) + (opening * 0.1) + (professionalism * 0.1)),
            "objection_handling": self._clamp_10((objections * 0.75) + (emotion_recovery * 0.15) + (objection_load * 0.2) + challenge_bonus),
            "closing": self._clamp_10((closing * 0.75) + (pitch * 0.1) + (emotion_recovery * 0.15) + (challenge_bonus * 0.5)),
        }

        return {
            "ended_at": session.ended_at or session.created_at,
            "overall_score": self._bounded_score(scorecard.overall_score, fallback=5.0),
            "professionalism": professionalism,
            "emotion_recovery": emotion_recovery,
            "objection_load": objection_load,
            "scenario_difficulty": scenario_difficulty,
            "scenario_factors": scenario_factors,
            "skills": skills,
        }

    def _build_skill_profile(self, snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not snapshots:
            return {
                "opening": self._skill_node("opening", 5.4, 0.0, 0.0, ["starting baseline"]),
                "rapport": self._skill_node("rapport", 5.2, 0.0, 0.0, ["starting baseline"]),
                "pitch_clarity": self._skill_node("pitch_clarity", 5.0, 0.0, 0.0, ["starting baseline"]),
                "objection_handling": self._skill_node("objection_handling", 4.9, 0.0, 0.0, ["starting baseline"]),
                "closing": self._skill_node("closing", 4.8, 0.0, 0.0, ["starting baseline"]),
            }

        weighted_histories: dict[str, list[float]] = {skill: [] for skill in SKILL_ORDER}
        weights = list(range(1, len(snapshots) + 1))
        professionalism_avg = self._mean(snapshot["professionalism"] for snapshot in snapshots)

        for index, snapshot in enumerate(snapshots):
            for skill in SKILL_ORDER:
                weighted_histories[skill].append(snapshot["skills"][skill] * weights[index])

        direct_scores = {
            skill: self._safe_divide(sum(weighted_histories[skill]), sum(weights)) for skill in SKILL_ORDER
        }
        propagated_scores = dict(direct_scores)
        propagated_scores["rapport"] = self._clamp_10((direct_scores["rapport"] * 0.7) + (direct_scores["opening"] * 0.2) + (professionalism_avg * 0.1))
        propagated_scores["pitch_clarity"] = self._clamp_10(
            (direct_scores["pitch_clarity"] * 0.75) + (propagated_scores["rapport"] * 0.15) + (direct_scores["opening"] * 0.1)
        )
        propagated_scores["objection_handling"] = self._clamp_10(
            (direct_scores["objection_handling"] * 0.75) + (propagated_scores["pitch_clarity"] * 0.15) + (propagated_scores["rapport"] * 0.1)
        )
        propagated_scores["closing"] = self._clamp_10(
            (direct_scores["closing"] * 0.7) + (propagated_scores["objection_handling"] * 0.2) + (propagated_scores["rapport"] * 0.1)
        )
        propagated_scores["opening"] = self._clamp_10((direct_scores["opening"] * 0.85) + (propagated_scores["rapport"] * 0.15))

        return {
            skill: self._skill_node(
                skill,
                propagated_scores[skill],
                self._skill_trend(snapshots, skill),
                min(1.0, len(snapshots) / 4),
                self._contributing_metrics(skill),
            )
            for skill in SKILL_ORDER
        }

    def _recommend_scenarios(
        self,
        *,
        scenarios: list[Scenario],
        skill_profile: dict[str, dict[str, Any]],
        recommended_difficulty: int,
        target_difficulty_factors: dict[str, Any],
        weakest_skills: list[str],
    ) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for scenario in scenarios:
            factors = self._scenario_difficulty_factors(scenario)
            focus = self._scenario_skill_focus(scenario)
            weakness_alignment = self._mean((10.0 - skill_profile[skill]["score"]) * weight for skill, weight in focus.items() if weight > 0)
            difficulty_fit = self._mean(
                [
                    5 - abs(scenario.difficulty - recommended_difficulty),
                    5 - abs(factors["objection_frequency"] - target_difficulty_factors["objection_frequency"]),
                    5 - abs(factors["homeowner_resistance_level"] - target_difficulty_factors["homeowner_resistance_level"]),
                    5 - abs(factors["scenario_complexity"] - target_difficulty_factors["scenario_complexity"]),
                    5 - abs(factors["patience_window"]["score"] - target_difficulty_factors["patience_window"]["score"]),
                ]
            )
            targeted_weaknesses = [skill for skill in weakest_skills if focus.get(skill, 0.0) >= 0.18]
            recommendation_score = round(self._clamp_10((weakness_alignment * 0.75) + (difficulty_fit * 0.65)), 2)
            focus_skills = [skill for skill, weight in sorted(focus.items(), key=lambda item: item[1], reverse=True) if weight >= 0.18]
            recommendations.append(
                {
                    "scenario_id": scenario.id,
                    "scenario_name": scenario.name,
                    "difficulty": int(scenario.difficulty),
                    "recommendation_score": recommendation_score,
                    "focus_skills": focus_skills,
                    "target_weaknesses": targeted_weaknesses or weakest_skills[:1],
                    "difficulty_factors": factors,
                    "rationale": self._recommendation_rationale(focus_skills, targeted_weaknesses or weakest_skills[:1], factors),
                }
            )
        return sorted(recommendations, key=lambda item: (item["recommendation_score"], -item["difficulty"]), reverse=True)[:5]

    def _recommended_difficulty(self, *, skill_profile: dict[str, dict[str, Any]], performance_trend: float) -> int:
        readiness = self._mean(node["score"] for node in skill_profile.values())
        weakest = min(node["score"] for node in skill_profile.values())
        difficulty = 1 + int(max(0.0, readiness - 5.0) // 1.1)
        if performance_trend > 0.35 and readiness >= 6.5:
            difficulty += 1
        if weakest < 5.2:
            difficulty -= 1
        return max(1, min(5, difficulty))

    def _target_difficulty_factors(self, *, skill_profile: dict[str, dict[str, Any]], recommended_difficulty: int) -> dict[str, Any]:
        weakest_skills = [node["skill"] for node in sorted(skill_profile.values(), key=lambda item: item["score"])[:2]]
        objection_frequency = max(1, min(5, recommended_difficulty + (1 if "objection_handling" in weakest_skills else 0)))
        resistance = max(
            1,
            min(
                5,
                recommended_difficulty + (1 if any(skill in weakest_skills for skill in {"opening", "rapport"}) else 0),
            ),
        )
        patience_score = max(
            1,
            min(
                5,
                6 - recommended_difficulty - (1 if any(skill in weakest_skills for skill in {"opening", "rapport"}) else 0),
            ),
        )
        complexity = max(1, min(5, recommended_difficulty + (1 if "closing" in weakest_skills else 0)))
        return {
            "objection_frequency": objection_frequency,
            "homeowner_resistance_level": resistance,
            "patience_window": {"label": self._patience_label(patience_score), "score": patience_score},
            "scenario_complexity": complexity,
        }

    def _scenario_difficulty_factors(self, scenario: Scenario | None) -> dict[str, Any]:
        if scenario is None:
            return {
                "objection_frequency": 1,
                "homeowner_resistance_level": 3,
                "patience_window": {"label": "medium", "score": 3},
                "scenario_complexity": 1,
            }

        persona = scenario.persona or {}
        concerns = persona.get("concerns", [])
        concern_count = len(concerns) if isinstance(concerns, list) else 0
        attitude = str(persona.get("attitude", "neutral")).lower()
        objection_stage = any("objection" in stage for stage in (scenario.stages or []))
        objection_frequency = max(1, min(5, concern_count + (1 if objection_stage else 0) or 1))
        resistance = max(1, min(5, ATTITUDE_RESISTANCE.get(attitude, 3) + (1 if scenario.difficulty >= 4 else 0)))
        patience_score = max(1, min(5, ATTITUDE_PATIENCE.get(attitude, 3) - (1 if scenario.difficulty >= 4 else 0)))
        complexity = round(min(5.0, (scenario.difficulty * 0.8) + (len(scenario.stages or []) * 0.25) + (concern_count * 0.35)))
        return {
            "objection_frequency": int(max(1, complexity if objection_frequency == 0 else objection_frequency)),
            "homeowner_resistance_level": resistance,
            "patience_window": {"label": self._patience_label(patience_score), "score": patience_score},
            "scenario_complexity": max(1, complexity),
        }

    def _scenario_skill_focus(self, scenario: Scenario) -> dict[str, float]:
        focus = {skill: 0.0 for skill in SKILL_ORDER}
        stages = scenario.stages or []
        persona = scenario.persona or {}
        concerns = persona.get("concerns", []) if isinstance(persona.get("concerns", []), list) else []
        attitude = str(persona.get("attitude", "neutral")).lower()

        if any(token in stage for stage in stages for token in ("door", "initial", "pitch")):
            focus["opening"] += 1.0
            focus["pitch_clarity"] += 0.9
        if any("close" in stage for stage in stages):
            focus["closing"] += 1.2
        if any("objection" in stage for stage in stages) or concerns:
            focus["objection_handling"] += 1.2
        if attitude in {"skeptical", "busy", "annoyed", "hostile"}:
            focus["rapport"] += 0.9
            focus["opening"] += 0.4
        if any(concern in {"trust", "price"} for concern in concerns):
            focus["pitch_clarity"] += 0.4
            focus["objection_handling"] += 0.3
        if any(concern in {"spouse", "incumbent_provider", "timing"} for concern in concerns):
            focus["closing"] += 0.4
            focus["objection_handling"] += 0.5

        total = sum(focus.values()) or 1.0
        return {skill: round(value / total, 3) for skill, value in focus.items()}

    def _extract_emotions(self, session: DrillSession) -> tuple[str, str]:
        emotion_events = [
            event.payload.get("emotion")
            for event in session.events
            if event.event_type == "server.session.state" and event.payload.get("emotion")
        ]
        if not emotion_events:
            return "neutral", "neutral"
        return str(emotion_events[0]), str(emotion_events[-1])

    def _emotion_recovery_score(self, start: str, end: str) -> float:
        start_resistance = EMOTION_RESISTANCE.get(start, 3)
        end_resistance = EMOTION_RESISTANCE.get(end, start_resistance)
        improvement = max(0, start_resistance - end_resistance)
        regression = max(0, end_resistance - start_resistance)
        return self._clamp_10(6.0 + (improvement * 1.1) - (regression * 0.9))

    def _compute_performance_trend(self, snapshots: list[dict[str, Any]]) -> float:
        if len(snapshots) < 2:
            return 0.0
        midpoint = max(1, len(snapshots) // 2)
        earlier = self._mean(snapshot["overall_score"] for snapshot in snapshots[:midpoint])
        later = self._mean(snapshot["overall_score"] for snapshot in snapshots[midpoint:])
        return round(later - earlier, 2)

    def _skill_trend(self, snapshots: list[dict[str, Any]], skill: str) -> float:
        if len(snapshots) < 2:
            return 0.0
        midpoint = max(1, len(snapshots) // 2)
        earlier = self._mean(snapshot["skills"][skill] for snapshot in snapshots[:midpoint])
        later = self._mean(snapshot["skills"][skill] for snapshot in snapshots[midpoint:])
        return round(later - earlier, 2)

    def _default_target_score(self, skill_profile: list[dict[str, Any]]) -> float:
        weakest = min(node["score"] for node in skill_profile) if skill_profile else 5.0
        return round(max(6.5, min(9.0, weakest + 1.0)), 1)

    def _recommendation_rationale(
        self,
        focus_skills: list[str],
        targeted_weaknesses: list[str],
        factors: dict[str, Any],
    ) -> str:
        focus = ", ".join(focus_skills[:2]) or "core selling fundamentals"
        weaknesses = ", ".join(targeted_weaknesses[:2]) or "current growth areas"
        return (
            f"Targets {weaknesses} through {focus} under resistance level "
            f"{factors['homeowner_resistance_level']} and complexity {factors['scenario_complexity']}."
        )

    def _contributing_metrics(self, skill: str) -> list[str]:
        metrics = {
            "opening": ["opening", "emotion recovery"],
            "rapport": ["opening", "professionalism", "emotion recovery"],
            "pitch_clarity": ["pitch delivery", "opening", "professionalism"],
            "objection_handling": ["objection handling", "objection load", "emotion recovery"],
            "closing": ["closing technique", "pitch delivery", "emotion recovery"],
        }
        return metrics[skill]

    def _skill_node(self, skill: str, score: float, trend: float, confidence: float, metrics: list[str]) -> dict[str, Any]:
        return {
            "skill": skill,
            "score": round(self._clamp_10(score), 2),
            "trend": round(trend, 2),
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "contributing_metrics": metrics,
        }

    def _bounded_score(self, value: Any, *, fallback: float) -> float:
        if isinstance(value, dict):
            value = value.get("score")
        try:
            return self._clamp_10(float(value))
        except (TypeError, ValueError):
            return fallback

    def _clamp_10(self, value: float) -> float:
        return max(0.0, min(10.0, value))

    def _mean(self, values) -> float:
        values = list(values)
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _safe_divide(self, numerator: float, denominator: float) -> float:
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def _patience_label(self, score: int) -> str:
        if score <= 2:
            return "short"
        if score == 3:
            return "medium"
        return "long"
