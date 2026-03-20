from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DoorDrill Backend"
    environment: str = "dev"
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        alias="CORS_ORIGINS",
    )
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
    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")
    sentry_traces_sample_rate: float = Field(default=0.1, alias="SENTRY_TRACES_SAMPLE_RATE")

    auth_required: bool = Field(default=False, alias="AUTH_REQUIRED")
    auth_mode: str = Field(default="headers", alias="AUTH_MODE")
    jwt_secret: str | None = Field(default="dev-jwt-secret-change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    max_upload_size_bytes: int = Field(default=5_242_880, alias="MAX_UPLOAD_SIZE_BYTES")
    jwt_audience: str | None = Field(default=None, alias="JWT_AUDIENCE")
    jwt_issuer: str | None = Field(default=None, alias="JWT_ISSUER")
    jwt_jwks_url: str | None = Field(default=None, alias="JWT_JWKS_URL")
    access_token_ttl_minutes: int = Field(default=30, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=14, alias="REFRESH_TOKEN_TTL_DAYS")
    invite_ttl_days: int = Field(default=7, alias="INVITE_TTL_DAYS")
    invite_deep_link_base: str = Field(default="doordrill://invite", alias="INVITE_DEEP_LINK_BASE")

    stt_provider: str = Field(default="mock", alias="STT_PROVIDER")
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    tts_provider: str = Field(default="mock", alias="TTS_PROVIDER")

    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    deepgram_base_url: str = Field(default="https://api.deepgram.com", alias="DEEPGRAM_BASE_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    grading_model: str = Field(default="gpt-4o-mini", alias="GRADING_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-5-sonnet-latest", alias="ANTHROPIC_MODEL")
    anthropic_chat_classification_model: str = Field(
        default="claude-3-5-haiku-latest",
        alias="ANTHROPIC_CHAT_CLASSIFICATION_MODEL",
    )
    anthropic_chat_answer_model: str = Field(
        default="claude-3-5-sonnet-latest",
        alias="ANTHROPIC_CHAT_ANSWER_MODEL",
    )
    anthropic_base_url: str = Field(default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")
    manager_ai_model: str | None = Field(default=None, alias="MANAGER_AI_MODEL")
    manager_ai_fast_model: str | None = Field(default=None, alias="MANAGER_AI_FAST_MODEL")
    manager_ai_fallback_provider: str | None = Field(default=None, alias="MANAGER_AI_FALLBACK_PROVIDER")
    manager_ai_fallback_model: str | None = Field(default=None, alias="MANAGER_AI_FALLBACK_MODEL")
    manager_ai_fallback_fast_model: str | None = Field(default=None, alias="MANAGER_AI_FALLBACK_FAST_MODEL")
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str | None = Field(default=None, alias="ELEVENLABS_VOICE_ID")
    elevenlabs_model_id: str = Field(default="eleven_flash_v2_5", alias="ELEVENLABS_MODEL_ID")
    elevenlabs_base_url: str = Field(default="https://api.elevenlabs.io", alias="ELEVENLABS_BASE_URL")
    deepgram_model: str = Field(default="nova-3", alias="DEEPGRAM_MODEL")
    stt_endpointing_ms: int = Field(default=360, alias="STT_ENDPOINTING_MS")
    stt_utterance_end_ms: int = Field(default=1100, alias="STT_UTTERANCE_END_MS")
    stt_vad_finalize_debounce_ms: int = Field(default=90, alias="STT_VAD_FINALIZE_DEBOUNCE_MS")
    homeowner_llm_temperature: float = Field(default=0.35, alias="HOMEOWNER_LLM_TEMPERATURE")
    elevenlabs_voice_stability: float = Field(default=0.42, alias="ELEVENLABS_VOICE_STABILITY")
    elevenlabs_voice_similarity_boost: float = Field(default=0.82, alias="ELEVENLABS_VOICE_SIMILARITY_BOOST")
    elevenlabs_streaming_latency_mode: int = Field(default=3, alias="ELEVENLABS_STREAMING_LATENCY_MODE")
    provider_timeout_seconds: float = Field(default=10.0, alias="PROVIDER_TIMEOUT_SECONDS")
    grading_timeout_seconds: float = Field(default=20.0, alias="GRADING_TIMEOUT_SECONDS")

    use_celery: bool = Field(default=False, alias="USE_CELERY")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")
    whisper_cleanup_enabled: bool = Field(default=False, alias="WHISPER_CLEANUP_ENABLED")
    whisper_model: str = Field(default="gpt-4o-mini-transcribe", alias="WHISPER_MODEL")
    manager_notification_email_enabled: bool = Field(default=False, alias="MANAGER_NOTIFICATION_EMAIL_ENABLED")
    manager_notification_push_enabled: bool = Field(default=False, alias="MANAGER_NOTIFICATION_PUSH_ENABLED")
    notification_email_provider: str = Field(default="sendgrid", alias="NOTIFICATION_EMAIL_PROVIDER")
    notification_push_provider: str = Field(default="expo", alias="NOTIFICATION_PUSH_PROVIDER")
    notification_max_retries: int = Field(default=5, alias="NOTIFICATION_MAX_RETRIES")
    notification_retry_base_seconds: int = Field(default=30, alias="NOTIFICATION_RETRY_BASE_SECONDS")
    management_analytics_cache_ttl_seconds: int = Field(default=60, alias="MANAGEMENT_ANALYTICS_CACHE_TTL_SECONDS")
    management_analytics_cache_max_entries: int = Field(default=512, alias="MANAGEMENT_ANALYTICS_CACHE_MAX_ENTRIES")
    management_analytics_warn_ms: int = Field(default=800, alias="MANAGEMENT_ANALYTICS_WARN_MS")
    management_analytics_critical_ms: int = Field(default=1500, alias="MANAGEMENT_ANALYTICS_CRITICAL_MS")
    sendgrid_api_key: str | None = Field(default=None, alias="SENDGRID_API_KEY")
    sendgrid_from_email: str | None = Field(default=None, alias="SENDGRID_FROM_EMAIL")
    ses_smtp_host: str = Field(default="email-smtp.us-east-1.amazonaws.com", alias="SES_SMTP_HOST")
    ses_smtp_port: int = Field(default=587, alias="SES_SMTP_PORT")
    ses_smtp_username: str | None = Field(default=None, alias="SES_SMTP_USERNAME")
    ses_smtp_password: str | None = Field(default=None, alias="SES_SMTP_PASSWORD")
    ses_from_email: str | None = Field(default=None, alias="SES_FROM_EMAIL")
    fcm_server_key: str | None = Field(default=None, alias="FCM_SERVER_KEY")
    fcm_base_url: str = Field(default="https://fcm.googleapis.com/fcm/send", alias="FCM_BASE_URL")
    expo_push_base_url: str = Field(default="https://exp.host/--/api/v2/push/send", alias="EXPO_PUSH_BASE_URL")
    expo_push_access_token: str | None = Field(default=None, alias="EXPO_PUSH_ACCESS_TOKEN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=True, alias="LOG_JSON")


@lru_cache
def get_settings() -> Settings:
    return Settings()
