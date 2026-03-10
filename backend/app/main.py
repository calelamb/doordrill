from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.manager import router as manager_router
from app.api.rep import router as rep_router
from app.api.scenarios import router as scenarios_router
from app.core.auth import get_actor
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.db.init_db import init_db
from app.middleware.request_logging import RequestLoggingMiddleware
from app.voice.ws import router as ws_router

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.logger = logging.getLogger("doordrill.api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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

@app.get("/uploads/{file_path:path}")
def serve_upload(
    file_path: str,
    actor=Depends(get_actor),
):
    import os

    safe_path = os.path.normpath(file_path)
    if safe_path.startswith("..") or safe_path.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid path")
    full_path = os.path.join("uploads", safe_path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(full_path)
