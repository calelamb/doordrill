import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.models.user import User
from app.models.scenario import Scenario
from app.models.assignment import Assignment
from app.models.types import AssignmentStatus
import datetime

db = SessionLocal()
rep = db.query(User).filter(User.email == "slo-rep@doordrill.local").first()
scenario = db.query(Scenario).filter(Scenario.name == "SLO Harness Scenario").first()

if rep and scenario:
    assignment = db.query(Assignment).filter(Assignment.rep_id == rep.id).first()
    if not assignment:
        assignment = Assignment(
            rep_id=rep.id,
            scenario_id=scenario.id,
            assigned_by=scenario.created_by_id,
            status=AssignmentStatus.ASSIGNED,
            min_score_target=80.0,
            due_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
        )
        db.add(assignment)
        db.commit()
        print("Assignment created successfully!")
    else:
        print("Assignment already exists!")
else:
    print("Rep or scenario not found. Run seed_load_data.py first.")
db.close()
