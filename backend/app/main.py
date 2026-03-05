from fastapi import FastAPI

from app.api.manager import router as manager_router
from app.api.rep import router as rep_router
from app.core.config import get_settings
from app.db.init_db import init_db
from app.voice.ws import router as ws_router

settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(manager_router)
app.include_router(rep_router)
app.include_router(ws_router)
