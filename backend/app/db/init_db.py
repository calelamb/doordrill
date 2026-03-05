from app.db.session import engine
from app.models import Base  # noqa: F401 - ensure models imported


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
