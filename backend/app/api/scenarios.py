from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_manager, require_rep_or_manager
from app.db.session import get_db
from app.models.scenario import Scenario
from app.models.user import User
from app.schemas.scenario import ObjectionTypeResponse, ScenarioCreateRequest, ScenarioResponse, ScenarioUpdateRequest
from app.services.objection_taxonomy_service import ObjectionTaxonomyService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
taxonomy_service = ObjectionTaxonomyService()


def _get_user_or_404(db: Session, user_id: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


def _ensure_same_org(actor: Actor, org_id: str | None) -> None:
    if actor.org_id and org_id and actor.org_id != org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")


@router.get("", response_model=list[ScenarioResponse])
def list_scenarios(
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
    org_id: str | None = Query(default=None),
) -> list[Scenario]:
    target_org = org_id or actor.org_id
    if target_org:
        _ensure_same_org(actor, target_org)
        return db.scalars(select(Scenario).where(Scenario.org_id == target_org).order_by(Scenario.created_at.desc())).all()
    return db.scalars(select(Scenario).order_by(Scenario.created_at.desc())).all()


@router.get("/objection-types", response_model=list[ObjectionTypeResponse])
def list_objection_types(
    actor: Actor = Depends(require_rep_or_manager),
    db: Session = Depends(get_db),
    industry: str | None = Query(default=None),
) -> list[ObjectionTypeResponse]:
    if taxonomy_service.ensure_seed_data(db):
        db.commit()
    return taxonomy_service.list_types(db, org_id=actor.org_id, industry=industry)


@router.get("/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(scenario_id: str, actor: Actor = Depends(require_rep_or_manager), db: Session = Depends(get_db)) -> Scenario:
    scenario = db.scalar(select(Scenario).where(Scenario.id == scenario_id))
    if scenario is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    _ensure_same_org(actor, scenario.org_id)
    return scenario


@router.post("", response_model=ScenarioResponse)
def create_scenario(
    payload: ScenarioCreateRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> Scenario:
    if actor.user_id and actor.role == "manager" and actor.user_id != payload.created_by_id:
        raise HTTPException(status_code=403, detail="manager can only create as themselves")

    creator = _get_user_or_404(db, payload.created_by_id)
    _ensure_same_org(actor, creator.org_id)

    scenario = Scenario(
        org_id=creator.org_id,
        name=payload.name,
        industry=payload.industry,
        difficulty=payload.difficulty,
        description=payload.description,
        persona=payload.persona,
        rubric=payload.rubric,
        stages=payload.stages,
        created_by_id=creator.id,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


@router.put("/{scenario_id}", response_model=ScenarioResponse)
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdateRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> Scenario:
    scenario = db.scalar(select(Scenario).where(Scenario.id == scenario_id))
    if scenario is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    _ensure_same_org(actor, scenario.org_id)

    for field in ("name", "industry", "difficulty", "description", "persona", "rubric", "stages"):
        value = getattr(payload, field)
        if value is not None:
            setattr(scenario, field, value)

    db.commit()
    db.refresh(scenario)
    return scenario
