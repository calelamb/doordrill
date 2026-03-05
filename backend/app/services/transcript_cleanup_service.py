from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.session import SessionArtifact, SessionTurn
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class TranscriptCleanupService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = StorageService()

    async def cleanup_session_transcript(self, db: Session, session_id: str) -> SessionArtifact:
        turns = db.scalars(
            select(SessionTurn).where(SessionTurn.session_id == session_id).order_by(SessionTurn.turn_index.asc())
        ).all()
        cleaned_turns = [
            {
                "turn_id": turn.id,
                "turn_index": turn.turn_index,
                "speaker": turn.speaker.value,
                "stage": turn.stage,
                "text": self._normalize_text(turn.text),
            }
            for turn in turns
        ]

        whisper_text = await self._try_whisper_full_transcript(db, session_id)
        metadata: dict[str, Any] = {
            "turn_count": len(cleaned_turns),
            "cleaned_turns": cleaned_turns,
            "source": "whisper" if whisper_text else "fallback",
        }
        if whisper_text:
            metadata["whisper_text"] = whisper_text

        artifact = SessionArtifact(
            session_id=session_id,
            artifact_type="transcript_cleanup",
            storage_key=f"sessions/{session_id}/cleanup_transcript.json",
            metadata_json=metadata,
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        return artifact

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.strip().split())

    async def _try_whisper_full_transcript(self, db: Session, session_id: str) -> str | None:
        if not self.settings.whisper_cleanup_enabled or not self.settings.openai_api_key:
            return None

        audio_artifact = db.scalar(
            select(SessionArtifact)
            .where(SessionArtifact.session_id == session_id, SessionArtifact.artifact_type == "audio")
            .order_by(SessionArtifact.created_at.desc())
        )
        if audio_artifact is None:
            return None

        audio_url = self.storage.get_presigned_url(audio_artifact.storage_key, ttl_seconds=120)
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                audio_resp = await client.get(audio_url)
                if audio_resp.status_code != 200:
                    return None
                audio_bytes = audio_resp.content

                files = {"file": ("session_audio.opus", audio_bytes, "audio/ogg")}
                data = {"model": self.settings.whisper_model}
                headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
                transcribe_resp = await client.post(
                    f"{self.settings.openai_base_url.rstrip('/')}/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                transcribe_resp.raise_for_status()
                payload = transcribe_resp.json()
        except Exception:  # pragma: no cover - network/provider dependent
            logger.warning("Whisper transcript cleanup failed", extra={"session_id": session_id})
            return None

        text = payload.get("text")
        return str(text).strip() if text else None
