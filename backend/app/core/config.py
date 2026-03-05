from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DoorDrill Backend"
    environment: str = "dev"
    database_url: str = Field(default="sqlite:///./doordrill.db", alias="DATABASE_URL")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    storage_bucket: str = Field(default="doordrill-session-artifacts", alias="STORAGE_BUCKET")
    ws_flush_interval_ms: int = Field(default=350, alias="WS_FLUSH_INTERVAL_MS")
    max_ws_event_batch: int = Field(default=200, alias="MAX_WS_EVENT_BATCH")

    auth_required: bool = Field(default=False, alias="AUTH_REQUIRED")

    stt_provider: str = Field(default="mock", alias="STT_PROVIDER")
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    tts_provider: str = Field(default="mock", alias="TTS_PROVIDER")

    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str | None = Field(default=None, alias="ELEVENLABS_VOICE_ID")


@lru_cache
def get_settings() -> Settings:
    return Settings()
