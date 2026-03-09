from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.scenario import Scenario


def test_rep_scenarios_include_org_and_global_sorted_by_difficulty(client, seed_org):
    db = SessionLocal()
    try:
        global_easy = Scenario(
            org_id=None,
            created_by_id=None,
            industry="pest_control",
            name="Friendly Homeowner",
            difficulty=1,
            description="A welcoming homeowner gives the rep a clean first rep.",
            persona={"attitude": "friendly"},
            rubric={"opening": 10},
            stages=["door_knock"],
        )
        org_hard = Scenario(
            org_id=seed_org["org_id"],
            created_by_id=seed_org["manager_id"],
            industry="pest_control",
            name="Hard Close",
            difficulty=4,
            description="A tougher scenario for advanced reps.",
            persona={"attitude": "guarded"},
            rubric={"closing": 10},
            stages=["close_attempt"],
        )
        db.add_all([global_easy, org_hard])
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/rep/scenarios",
        headers={"x-user-id": seed_org["rep_id"], "x-user-role": "rep"},
    )

    assert response.status_code == 200
    body = response.json()
    names = [item["name"] for item in body]

    assert "Friendly Homeowner" in names
    assert "Hard Close" in names
    assert body[0]["difficulty"] <= body[-1]["difficulty"]
