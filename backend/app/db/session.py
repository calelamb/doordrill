from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
is_sqlite = settings.database_url.startswith("sqlite")
connect_args: dict = {}
if is_sqlite:
    connect_args = {"check_same_thread": False}
else:
    connect_args = {"sslmode": "require"}

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    # SQLite is heavily used in local dev and tests; a single pooled
    # connection causes dashboard streams to starve normal API requests.
    pool_size=10 if not is_sqlite else 5,
    max_overflow=20 if not is_sqlite else 5,
    pool_timeout=30,
    pool_recycle=1800,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
