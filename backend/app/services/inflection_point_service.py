from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.session import SessionArtifact
from app.services.turn_enrichment_service import ReconstructedTimeline, TurnCommitContext

EMOTION_ORDER = ["interested", "curious", "neutral", "skeptical", "annoyed", "hostile"]
INFLECTION_COACHING_NOTES = {
    ("negative", "pushes_close"): "Rep pushed for a close before earning trust - homeowner hardened.",
    ("negative", "dismisses_concern"): "Rep brushed off the homeowner's concern - caused immediate resistance.",
    ("negative", "ignores_objection"): "Rep dodged the active objection - homeowner noticed and pushed back harder.",
    ("negative", "neutral_delivery"): "Rep gave a generic answer when the homeowner needed something specific.",
    ("positive", "acknowledges_concern"): "Rep acknowledged the concern directly - broke the resistance.",
    ("positive", "provides_proof"): "Rep backed up a claim - homeowner's skepticism dropped.",
    ("positive", "reduces_pressure"): "Rep took pressure off - homeowner opened up.",
    ("positive", "mentions_social_proof"): "Rep's neighbor reference landed - homeowner became curious.",
}


@dataclass
class InflectionPoint:
    turn_index: int
    rep_turn_id: str
    ai_turn_id: str
    direction: str
    emotion_before: str
    emotion_after: str
    pressure_before: int
    pressure_after: int
    behavioral_signals: list[str]
    coaching_label: str
    coaching_note: str


class InflectionPointService:
    def analyze(self, timeline: ReconstructedTimeline) -> list[InflectionPoint]:
        candidates: list[tuple[int, InflectionPoint]] = []
        for turn_index, context in enumerate(timeline.turn_contexts, start=1):
            direction = self._classify_direction(context)
            if direction is None:
                continue
            point = self._build_inflection(turn_index=turn_index, context=context, direction=direction)
            candidates.append((self._severity(context), point))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [point for _, point in candidates[:3]]

    def write_session_artifact(
        self,
        db: Session,
        *,
        session_id: str,
        timeline: ReconstructedTimeline,
    ) -> SessionArtifact:
        inflection_points = self.analyze(timeline)
        artifact = db.scalar(
            select(SessionArtifact)
            .where(SessionArtifact.session_id == session_id, SessionArtifact.artifact_type == "inflection_points")
            .order_by(SessionArtifact.created_at.desc())
        )
        if artifact is None:
            artifact = SessionArtifact(
                session_id=session_id,
                artifact_type="inflection_points",
                storage_key=f"session-artifacts/{session_id}/inflection_points.json",
                metadata_json={},
            )
            db.add(artifact)

        artifact.metadata_json = {
            "count": len(inflection_points),
            "points": [asdict(point) for point in inflection_points],
        }
        db.flush()
        return artifact

    def _classify_direction(self, context: TurnCommitContext) -> str | None:
        emotion_delta = self._emotion_delta(context)
        pressure_delta = self._pressure_delta(context)
        if emotion_delta >= 1 and pressure_delta >= 2:
            return "negative"
        if pressure_delta <= -2 or emotion_delta <= -2:
            return "positive"
        return None

    def _severity(self, context: TurnCommitContext) -> int:
        return abs(self._pressure_delta(context)) + abs(self._emotion_delta(context))

    def _emotion_delta(self, context: TurnCommitContext) -> int:
        before = self._emotion_index(context.emotion_before)
        after = self._emotion_index(context.emotion_after)
        return after - before

    def _pressure_delta(self, context: TurnCommitContext) -> int:
        return int(context.pressure_after or 0) - int(context.pressure_before or 0)

    def _emotion_index(self, emotion: str | None) -> int:
        try:
            return EMOTION_ORDER.index(str(emotion or "neutral"))
        except ValueError:
            return EMOTION_ORDER.index("neutral")

    def _build_inflection(
        self,
        *,
        turn_index: int,
        context: TurnCommitContext,
        direction: str,
    ) -> InflectionPoint:
        return InflectionPoint(
            turn_index=turn_index,
            rep_turn_id=context.rep_turn_id or "",
            ai_turn_id=context.ai_turn_id or "",
            direction=direction,
            emotion_before=context.emotion_before or "unknown",
            emotion_after=context.emotion_after or "unknown",
            pressure_before=int(context.pressure_before or 0),
            pressure_after=int(context.pressure_after or 0),
            behavioral_signals=list(context.behavioral_signals),
            coaching_label="Lost them here" if direction == "negative" else "Turned it around",
            coaching_note=self._generate_coaching_note(context=context, direction=direction),
        )

    def _generate_coaching_note(self, *, context: TurnCommitContext, direction: str) -> str:
        for signal in context.behavioral_signals:
            note = INFLECTION_COACHING_NOTES.get((direction, signal))
            if note:
                return note
        if direction == "negative":
            return "The turn increased resistance and pushed the homeowner further away."
        return "The turn reduced pressure or softened the homeowner's stance in a meaningful way."
