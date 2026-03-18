from dataclasses import dataclass
from typing import Optional


@dataclass
class TurnLatencyRecord:
    session_id: str
    turn_index: int

    # Timestamps (monotonic seconds)
    vad_end_ts: Optional[float] = None  # VAD speaking=false
    stt_final_ts: Optional[float] = None  # STT utterance finalized
    llm_first_token_ts: Optional[float] = None  # First token from LLM
    first_sentence_ts: Optional[float] = None  # First sentence boundary hit
    tts_task_created_ts: Optional[float] = None  # First TTS asyncio.Task created
    first_audio_byte_ts: Optional[float] = None  # First audio packet sent to client

    def log_summary(self, logger) -> None:
        if self.vad_end_ts is not None and self.first_audio_byte_ts is not None:
            total_ms = (self.first_audio_byte_ts - self.vad_end_ts) * 1000
            stt_ms = ((self.stt_final_ts or 0) - (self.vad_end_ts or 0)) * 1000
            llm_ms = ((self.llm_first_token_ts or 0) - (self.stt_final_ts or 0)) * 1000
            tts_ms = ((self.first_audio_byte_ts or 0) - (self.tts_task_created_ts or 0)) * 1000
            logger.info(
                "turn_latency",
                extra={
                    "session_id": self.session_id,
                    "turn_index": self.turn_index,
                    "total_ms": round(total_ms),
                    "stt_ms": round(stt_ms),
                    "llm_ms": round(llm_ms),
                    "tts_ms": round(tts_ms),
                },
            )
