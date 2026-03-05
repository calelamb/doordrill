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
    object_storage_endpoint: str | None = Field(default=None, alias="OBJECT_STORAGE_ENDPOINT")
    object_storage_region: str = Field(default="us-east-1", alias="OBJECT_STORAGE_REGION")
    object_storage_access_key: str | None = Field(default=None, alias="OBJECT_STORAGE_ACCESS_KEY")
    object_storage_secret_key: str | None = Field(default=None, alias="OBJECT_STORAGE_SECRET_KEY")
    object_storage_force_path_style: bool = Field(default=False, alias="OBJECT_STORAGE_FORCE_PATH_STYLE")
    object_storage_public_base_url: str | None = Field(default=None, alias="OBJECT_STORAGE_PUBLIC_BASE_URL")
    default_presign_ttl_seconds: int = Field(default=3600, alias="DEFAULT_PRESIGN_TTL_SECONDS")
    ws_flush_interval_ms: int = Field(default=350, alias="WS_FLUSH_INTERVAL_MS")
    max_ws_event_batch: int = Field(default=200, alias="MAX_WS_EVENT_BATCH")

    auth_required: bool = Field(default=False, alias="AUTH_REQUIRED")
    auth_mode: str = Field(default="headers", alias="AUTH_MODE")
    jwt_secret: str | None = Field(default="dev-jwt-secret-change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_audience: str | None = Field(default=None, alias="JWT_AUDIENCE")
    jwt_issuer: str | None = Field(default=None, alias="JWT_ISSUER")
    jwt_jwks_url: str | None = Field(default=None, alias="JWT_JWKS_URL")
    access_token_ttl_minutes: int = Field(default=30, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=14, alias="REFRESH_TOKEN_TTL_DAYS")

    stt_provider: str = Field(default="mock", alias="STT_PROVIDER")
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    tts_provider: str = Field(default="mock", alias="TTS_PROVIDER")

    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    deepgram_base_url: str = Field(default="https://api.deepgram.com", alias="DEEPGRAM_BASE_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-5-sonnet-latest", alias="ANTHROPIC_MODEL")
    anthropic_base_url: str = Field(default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str | None = Field(default=None, alias="ELEVENLABS_VOICE_ID")
    elevenlabs_model_id: str = Field(default="eleven_flash_v2_5", alias="ELEVENLABS_MODEL_ID")
    elevenlabs_base_url: str = Field(default="https://api.elevenlabs.io", alias="ELEVENLABS_BASE_URL")
    deepgram_model: str = Field(default="nova-2", alias="DEEPGRAM_MODEL")
    provider_timeout_seconds: float = Field(default=10.0, alias="PROVIDER_TIMEOUT_SECONDS")

    use_celery: bool = Field(default=False, alias="USE_CELERY")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")
    whisper_cleanup_enabled: bool = Field(default=False, alias="WHISPER_CLEANUP_ENABLED")
    whisper_model: str = Field(default="gpt-4o-mini-transcribe", alias="WHISPER_MODEL")
    manager_notification_email_enabled: bool = Field(default=False, alias="MANAGER_NOTIFICATION_EMAIL_ENABLED")
    manager_notification_push_enabled: bool = Field(default=False, alias="MANAGER_NOTIFICATION_PUSH_ENABLED")
    notification_max_retries: int = Field(default=5, alias="NOTIFICATION_MAX_RETRIES")
    notification_retry_base_seconds: int = Field(default=30, alias="NOTIFICATION_RETRY_BASE_SECONDS")
    sendgrid_api_key: str | None = Field(default=None, alias="SENDGRID_API_KEY")
    sendgrid_from_email: str | None = Field(default=None, alias="SENDGRID_FROM_EMAIL")
    expo_push_base_url: str = Field(default="https://exp.host/--/api/v2/push/send", alias="EXPO_PUSH_BASE_URL")
    expo_push_access_token: str | None = Field(default=None, alias="EXPO_PUSH_ACCESS_TOKEN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=True, alias="LOG_JSON")


@lru_cache
def get_settings() -> Settings:
    return Settings()
