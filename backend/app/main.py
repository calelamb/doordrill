from __future__ import annotations

import contextlib
import logging
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.manager import router as manager_router
from app.api.rep import router as rep_router
from app.api.scenarios import router as scenarios_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.db.init_db import init_db
from app.middleware.request_logging import RequestLoggingMiddleware
from app.voice.ws import router as ws_router

settings = get_settings()
configure_logging()


def validate_production_config() -> None:
    s = get_settings()
    if s.environment != "production":
        return

    errors: list[str] = []
    if s.stt_provider == "mock":
        errors.append("STT_PROVIDER must not be 'mock' in production")
    if s.llm_provider == "mock":
        errors.append("LLM_PROVIDER must not be 'mock' in production")
    if s.tts_provider == "mock":
        errors.append("TTS_PROVIDER must not be 'mock' in production")
    if not s.deepgram_api_key:
        errors.append("DEEPGRAM_API_KEY is required")
    if not s.openai_api_key and not s.anthropic_api_key:
        errors.append("At least one LLM API key (OPENAI_API_KEY or ANTHROPIC_API_KEY) is required")
    if not s.elevenlabs_api_key:
        errors.append("ELEVENLABS_API_KEY is required")
    if s.jwt_secret == "dev-jwt-secret-change-me":
        errors.append("JWT_SECRET must be changed from the default dev value")
    if not s.redis_url:
        errors.append("REDIS_URL is required in production")
    if s.database_url.startswith("sqlite"):
        errors.append("SQLite is not supported in production; set DATABASE_URL to a PostgreSQL URL")
    if errors:
        logger = logging.getLogger("doordrill.startup")
        for err in errors:
            logger.error("config_validation_error", extra={"error": err})
        raise RuntimeError(f"Production config validation failed: {'; '.join(errors)}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_production_config()
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)
app.logger = logging.getLogger("doordrill.api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Trace-Id"],
)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
async def health() -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = str(exc)

    if settings.redis_url:
        try:
            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
            await redis_client.ping()
            await redis_client.aclose()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = str(exc)

    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    code = 200 if status == "ok" else 503
    sha = ""
    with contextlib.suppress(Exception):
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    return JSONResponse({"status": status, "checks": checks, "sha": sha}, status_code=code)


app.include_router(admin_router)
app.include_router(manager_router)
app.include_router(rep_router)
app.include_router(auth_router)
app.include_router(scenarios_router)
app.include_router(ws_router)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
