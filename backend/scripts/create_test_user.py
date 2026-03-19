#!/usr/bin/env python3
"""
Creates a test organization, manager, and rep account for local/phone testing.
Run from the backend directory:
    python scripts/create_test_user.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import Organization, Team, User
from app.models.types import UserRole
from app.services.auth_service import AuthService

settings = get_settings()
auth_service = AuthService()

engine = create_engine(settings.database_url)

MANAGER_EMAIL = "manager@doordrill.test"
REP_EMAIL     = "rep@doordrill.test"
PASSWORD      = "Test1234!"
ORG_NAME      = "DoorDrill Test Org"

def run():
    with Session(engine) as db:
        # --- Org ---
        org = db.scalar(select(Organization).where(Organization.name == ORG_NAME))
        if not org:
            org = Organization(
                id=str(uuid.uuid4()),
                name=ORG_NAME,
                industry="solar",
                plan_tier="starter",
            )
            db.add(org)
            db.flush()
            print(f"✓ Created org: {org.name} ({org.id})")
        else:
            print(f"→ Org already exists: {org.name} ({org.id})")

        # --- Team ---
        team = db.scalar(select(Team).where(Team.org_id == org.id))
        if not team:
            team = Team(
                id=str(uuid.uuid4()),
                org_id=org.id,
                name="Test Team",
            )
            db.add(team)
            db.flush()
            print(f"✓ Created team: {team.name} ({team.id})")
        else:
            print(f"→ Team already exists: {team.name} ({team.id})")

        # --- Manager ---
        manager = db.scalar(select(User).where(User.email == MANAGER_EMAIL))
        if not manager:
            manager = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                team_id=team.id,
                role=UserRole.MANAGER,
                name="Test Manager",
                email=MANAGER_EMAIL,
                password_hash=auth_service.hash_password(PASSWORD),
                auth_provider="local",
            )
            db.add(manager)
            # Point team's manager_id at this user
            team.manager_id = manager.id
            print(f"✓ Created manager: {MANAGER_EMAIL}")
        else:
            # Reset password in case it changed
            manager.password_hash = auth_service.hash_password(PASSWORD)
            print(f"→ Manager already exists, password reset: {MANAGER_EMAIL}")

        # --- Rep ---
        rep = db.scalar(select(User).where(User.email == REP_EMAIL))
        if not rep:
            rep = User(
                id=str(uuid.uuid4()),
                org_id=org.id,
                team_id=team.id,
                role=UserRole.REP,
                name="Test Rep",
                email=REP_EMAIL,
                password_hash=auth_service.hash_password(PASSWORD),
                auth_provider="local",
            )
            db.add(rep)
            print(f"✓ Created rep: {REP_EMAIL}")
        else:
            rep.password_hash = auth_service.hash_password(PASSWORD)
            print(f"→ Rep already exists, password reset: {REP_EMAIL}")

        db.commit()

    print()
    print("━" * 40)
    print("LOGIN CREDENTIALS")
    print("━" * 40)
    print(f"  Manager → {MANAGER_EMAIL}")
    print(f"  Rep     → {REP_EMAIL}")
    print(f"  Password (both) → {PASSWORD}")
    print("━" * 40)

if __name__ == "__main__":
    run()
