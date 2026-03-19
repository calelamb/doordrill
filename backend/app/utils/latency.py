from dataclasses import dataclass
from typing import Optional


@dataclass
class TurnBudgetMetrics:
    stt_ms: int | None = None
    analysis_ms: int | None = None
    llm_first_token_ms: int | None = None
    tts_first_audio_ms: int | None = None
    total_turn_ms: int | None = None

    def to_payload(self) -> dict[str, int | None]:
        return {
            "stt_ms": self.stt_ms,
            "analysis_ms": self.analysis_ms,
            "llm_first_token_ms": self.llm_first_token_ms,
            "tts_first_audio_ms": self.tts_first_audio_ms,
            "total_turn_ms": self.total_turn_ms,
        }


@dataclass
class TurnLatencyRecord:
    session_id: str
    turn_index: int

    # Timestamps (monotonic seconds)
    vad_end_ts: Optional[float] = None  # VAD speaking=false
    stt_final_ts: Optional[float] = None  # STT utterance finalized
    analysis_complete_ts: Optional[float] = None  # Turn analysis + planning completed
    llm_first_token_ts: Optional[float] = None  # First token from LLM
    first_sentence_ts: Optional[float] = None  # First sentence boundary hit
    tts_task_created_ts: Optional[float] = None  # First TTS asyncio.Task created
    first_audio_byte_ts: Optional[float] = None  # First audio packet sent to client

    def to_budget_metrics(self) -> TurnBudgetMetrics:
        stt_ms = None
        analysis_ms = None
        llm_ms = None
        tts_ms = None
        total_ms = None
        if self.vad_end_ts is not None and self.stt_final_ts is not None:
            stt_ms = max(0, round((self.stt_final_ts - self.vad_end_ts) * 1000))
        if self.stt_final_ts is not None and self.analysis_complete_ts is not None:
            analysis_ms = max(0, round((self.analysis_complete_ts - self.stt_final_ts) * 1000))
        if self.analysis_complete_ts is not None and self.llm_first_token_ts is not None:
            llm_ms = max(0, round((self.llm_first_token_ts - self.analysis_complete_ts) * 1000))
        if self.tts_task_created_ts is not None and self.first_audio_byte_ts is not None:
            tts_ms = max(0, round((self.first_audio_byte_ts - self.tts_task_created_ts) * 1000))
        if self.vad_end_ts is not None and self.first_audio_byte_ts is not None:
            total_ms = max(0, round((self.first_audio_byte_ts - self.vad_end_ts) * 1000))
        return TurnBudgetMetrics(
            stt_ms=stt_ms,
            analysis_ms=analysis_ms,
            llm_first_token_ms=llm_ms,
            tts_first_audio_ms=tts_ms,
            total_turn_ms=total_ms,
        )

    def log_summary(self, logger) -> None:
        metrics = self.to_budget_metrics()
        if metrics.total_turn_ms is not None:
            logger.info(
                "turn_latency",
                extra={
                    "session_id": self.session_id,
                    "turn_index": self.turn_index,
                    "total_ms": metrics.total_turn_ms,
                    "stt_ms": metrics.stt_ms,
                    "analysis_ms": metrics.analysis_ms,
                    "llm_ms": metrics.llm_first_token_ms,
                    "tts_ms": metrics.tts_first_audio_ms,
                },
            )
