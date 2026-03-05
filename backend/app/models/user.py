import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import UserRole

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.manager_action import ManagerActionLog
    from app.models.scenario import Scenario
    from app.models.scorecard import ManagerReview
    from app.models.session import Session


def _uuid() -> str:
    return str(uuid.uuid4())


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False, default="pest_control")
    plan_tier: Mapped[str] = mapped_column(String(50), nullable=False, default="starter")

    teams: Mapped[list["Team"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    manager_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="teams")
    members: Mapped[list["User"]] = relationship(back_populates="team", foreign_keys="User.team_id")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="local")

    organization: Mapped[Organization] = relationship(back_populates="users")
    team: Mapped[Team | None] = relationship(back_populates="members", foreign_keys=[team_id])

    created_scenarios: Mapped[list["Scenario"]] = relationship(back_populates="created_by")
    assigned_by: Mapped[list["Assignment"]] = relationship(
        back_populates="assigned_by_user", foreign_keys="Assignment.assigned_by"
    )
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="rep", foreign_keys="Assignment.rep_id")
    sessions: Mapped[list["Session"]] = relationship(back_populates="rep")
    manager_reviews: Mapped[list["ManagerReview"]] = relationship(back_populates="reviewer")
    action_logs: Mapped[list["ManagerActionLog"]] = relationship(back_populates="manager")
