from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

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
logger = logging.getLogger("doordrill.startup")


def _validate_startup_security() -> None:
    """Fail fast on insecure configuration in non-dev environments."""
    if settings.environment in ("dev", "test"):
        if not settings.auth_required:
            logger.warning("AUTH_REQUIRED=False — acceptable for %s only", settings.environment)
        if not settings.jwt_secret:
            logger.warning("JWT_SECRET not set — auth endpoints will fail until configured")
        return

    # Production / staging guards
    if not settings.jwt_secret:
        raise RuntimeError(
            "JWT_SECRET must be set in production/staging. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if settings.jwt_secret == "dev-jwt-secret-change-me":
        raise RuntimeError("JWT_SECRET is still set to the development default — change it for production")
    if len(settings.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters (256 bits) for production")
    if not settings.auth_required:
        raise RuntimeError("AUTH_REQUIRED must be True in production/staging")
    if settings.auth_mode.lower() == "headers":
        raise RuntimeError("AUTH_MODE=headers is not allowed in production — use 'jwt'")
    if settings.database_url.startswith("sqlite"):
        logger.warning("SQLite is not recommended for production — use PostgreSQL")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.environment not in ("dev", "test"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    _validate_startup_security()
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.logger = logging.getLogger("doordrill.api")

# CORS: use configured origins for production, localhost for dev
_dev_origins = [
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
]
_cors_origins = settings.cors_allowed_origins if settings.cors_allowed_origins else _dev_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-ID", "X-User-Role"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(admin_router)
app.include_router(manager_router)
app.include_router(rep_router)
app.include_router(auth_router)
app.include_router(scenarios_router)
app.include_router(ws_router)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
