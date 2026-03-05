import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.user import Organization, User


def _uuid() -> str:
    return str(uuid.uuid4())


class Scenario(Base, TimestampMixin):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False, default="pest_control")
    difficulty: Mapped[int] = mapped_column(nullable=False, default=1)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    persona: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rubric: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    organization: Mapped["Organization | None"] = relationship()
    created_by: Mapped["User | None"] = relationship(back_populates="created_scenarios")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="scenario")
