#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal, engine
from app.models import Base
from app.models.scenario import Scenario
from app.models.types import UserRole
from app.models.user import Organization, Team, User

ORG_NAME = "DoorDrill SLO Org"
MANAGER_EMAIL = "slo-manager@doordrill.local"
REP_EMAIL = "slo-rep@doordrill.local"
SCENARIO_NAME = "SLO Harness Scenario"


def ensure_seed_data() -> dict[str, str]:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        org = db.scalar(select(Organization).where(Organization.name == ORG_NAME))
        if org is None:
            org = Organization(name=ORG_NAME, industry="pest_control", plan_tier="pro")
            db.add(org)
            db.flush()

        manager = db.scalar(select(User).where(User.email == MANAGER_EMAIL))
        if manager is None:
            manager = User(org_id=org.id, role=UserRole.MANAGER, name="SLO Manager", email=MANAGER_EMAIL)
            db.add(manager)
            db.flush()
        else:
            manager.org_id = org.id
            manager.role = UserRole.MANAGER

        rep = db.scalar(select(User).where(User.email == REP_EMAIL))
        if rep is None:
            rep = User(org_id=org.id, role=UserRole.REP, name="SLO Rep", email=REP_EMAIL)
            db.add(rep)
            db.flush()
        else:
            rep.org_id = org.id
            rep.role = UserRole.REP

        team = db.scalar(select(Team).where(Team.name == "SLO Team", Team.org_id == org.id))
        if team is None:
            team = Team(org_id=org.id, manager_id=manager.id, name="SLO Team")
            db.add(team)
            db.flush()
        else:
            team.manager_id = manager.id

        manager.team_id = team.id
        rep.team_id = team.id

        scenario = db.scalar(select(Scenario).where(Scenario.name == SCENARIO_NAME, Scenario.org_id == org.id))
        if scenario is None:
            scenario = Scenario(
                org_id=org.id,
                name=SCENARIO_NAME,
                industry="pest_control",
                difficulty=2,
                description="SLO load harness scenario.",
                persona={"attitude": "skeptical", "concerns": ["price"]},
                rubric={"opening": 10, "pitch": 10, "objections": 10, "closing": 10, "professionalism": 10},
                stages=["door_knock", "initial_pitch", "objection_handling", "close_attempt"],
                created_by_id=manager.id,
            )
            db.add(scenario)
            db.flush()
        else:
            scenario.created_by_id = manager.id

        db.commit()

        return {
            "org_id": org.id,
            "manager_id": manager.id,
            "rep_id": rep.id,
            "scenario_id": scenario.id,
        }
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed deterministic manager/rep/scenario identities for SLO harness")
    parser.add_argument(
        "--field",
        choices=["org_id", "manager_id", "rep_id", "scenario_id"],
        default="",
        help="Output only one field instead of full JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = ensure_seed_data()

    if args.field:
        print(data[args.field])
    else:
        print(json.dumps(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
