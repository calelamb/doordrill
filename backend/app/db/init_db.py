from sqlalchemy import select

from app.db.session import SessionLocal, engine
from app.models import Base  # noqa: F401 - ensure models imported
from app.models.prompt_version import PromptVersion
from app.models.scenario import Scenario
from app.services.analytics_refresh_service import AnalyticsRefreshService
from app.services.conversation_orchestrator import PromptBuilder
from app.services.grading_service import GradingPromptBuilder

PHASE_ONE_STAGES = [
    "door_knock",
    "initial_pitch",
    "objection_handling",
    "considering",
    "close_attempt",
    "ended",
]

STANDARD_RUBRIC = {
    "opening": {"weight": 0.15, "description": "Introduces self and earns attention cleanly."},
    "pitch_delivery": {"weight": 0.25, "description": "Explains value clearly and specifically."},
    "objection_handling": {"weight": 0.30, "description": "Addresses the homeowner's real concern directly."},
    "closing_technique": {"weight": 0.20, "description": "Asks for a realistic next step or close."},
    "professionalism": {"weight": 0.10, "description": "Stays calm, respectful, and credible."},
}

PHASE_ONE_SCENARIOS = [
    {
        "name": "Friendly First Door",
        "difficulty": 1,
        "description": "A friendly retired teacher answers the door and is open to hearing a short pitch.",
        "persona": {
            "name": "Linda Parker",
            "attitude": "friendly but practical",
            "concerns": ["value", "trust", "keeping the interaction simple"],
            "objection_queue": [],
            "buy_likelihood": "high",
            "softening_condition": "You become receptive when the rep is polite, specific, and offers an easy next step.",
        },
    },
    {
        "name": "Price Hawk",
        "difficulty": 2,
        "description": "A budget-conscious homeowner pushes on price and compares the offer to cheaper online options.",
        "persona": {
            "name": "Marcus Lee",
            "attitude": "skeptical and cost-focused",
            "concerns": ["price", "hidden fees", "whether local service is worth the premium"],
            "objection_queue": ["I can get it cheaper online"],
            "buy_likelihood": "medium-low",
            "softening_condition": "You soften when the rep explains real service differences and makes the economics concrete.",
        },
    },
    {
        "name": "Already Has Service",
        "difficulty": 2,
        "description": "An existing Orkin customer believes they are already covered and sees no reason to switch.",
        "persona": {
            "name": "Darren Brooks",
            "attitude": "confident and slightly dismissive",
            "concerns": ["disruption", "switching risk", "provider trust"],
            "objection_queue": ["I'm already covered", "We use Orkin already"],
            "buy_likelihood": "medium-low",
            "softening_condition": "You only reconsider if the rep uncovers a gap and makes the change feel low risk.",
        },
    },
    {
        "name": "Spouse Not Home",
        "difficulty": 3,
        "description": "A homeowner defers decisions and insists they need to speak with their husband first.",
        "persona": {
            "name": "Angela Torres",
            "attitude": "polite but deferential",
            "concerns": ["making decisions alone", "household coordination", "avoiding pressure"],
            "objection_queue": ["I need to talk to my husband first"],
            "buy_likelihood": "medium",
            "softening_condition": "You warm up when the rep lowers pressure and offers a simple, spouse-friendly next step.",
        },
    },
    {
        "name": "Bad Experience",
        "difficulty": 3,
        "description": "A skeptical retiree had a poor experience with a prior pest company and does not trust sales promises.",
        "persona": {
            "name": "Ronald Hayes",
            "attitude": "skeptical and slightly irritated",
            "concerns": ["wasted money", "broken promises", "service reliability"],
            "objection_queue": ["The last company wasted my money"],
            "buy_likelihood": "low",
            "softening_condition": "You respond when the rep acknowledges the bad experience and explains how service accountability is different.",
        },
    },
    {
        "name": "Busy Parent",
        "difficulty": 3,
        "description": "A rushed parent answers the door while multitasking and resists spending time on the conversation.",
        "persona": {
            "name": "Tanya Nguyen",
            "attitude": "hurried and impatient",
            "concerns": ["time", "interruption", "keeping the household moving"],
            "objection_queue": ["I don't have time for this"],
            "buy_likelihood": "medium-low",
            "softening_condition": "You stay engaged only if the rep is concise and quickly earns a reason for a follow-up.",
        },
    },
    {
        "name": "Environmentally Concerned",
        "difficulty": 4,
        "description": "A parent is worried about chemicals near children and needs a safety-first explanation before considering service.",
        "persona": {
            "name": "Melissa Carter",
            "attitude": "concerned and protective",
            "concerns": ["children", "pets", "chemicals", "long-term safety"],
            "objection_queue": ["I don't want chemicals near my kids"],
            "buy_likelihood": "low-medium",
            "softening_condition": "You soften only when the rep answers safety concerns directly and specifically without sounding evasive.",
        },
    },
    {
        "name": "Stacked Objections",
        "difficulty": 5,
        "description": "A high-friction homeowner combines price pressure, spouse deferral, and a prior bad experience.",
        "persona": {
            "name": "Kevin Foster",
            "attitude": "guarded and hard to win over",
            "concerns": ["price", "spouse approval", "trust after bad service", "risk of wasting money"],
            "objection_queue": [
                "I can get it cheaper online",
                "I need to talk to my wife first",
                "The last company wasted my money",
            ],
            "buy_likelihood": "low",
            "softening_condition": "You only move if the rep handles objections in sequence, stays calm, and reduces risk with a simple next step.",
        },
    },
]


def _upsert_prompt_version(db, *, prompt_type: str, version: str, content: str) -> None:
    existing = db.scalar(
        select(PromptVersion).where(
            PromptVersion.prompt_type == prompt_type,
            PromptVersion.version == version,
        )
    )
    if existing is None:
        existing = PromptVersion(
            prompt_type=prompt_type,
            version=version,
            content=content,
            active=True,
        )
        db.add(existing)
    else:
        existing.content = content
        existing.active = True

    for row in db.scalars(select(PromptVersion).where(PromptVersion.prompt_type == prompt_type)).all():
        row.active = row.version == version


def _seed_prompt_versions(db) -> None:
    _upsert_prompt_version(
        db,
        prompt_type="conversation",
        version="conversation_v1",
        content=PromptBuilder.template_blueprint(),
    )
    _upsert_prompt_version(
        db,
        prompt_type="grading",
        version="grading_v1",
        content=GradingPromptBuilder.template_blueprint(),
    )


def _seed_phase_one_scenarios(db) -> None:
    for payload in PHASE_ONE_SCENARIOS:
        scenario = db.scalar(
            select(Scenario).where(
                Scenario.org_id.is_(None),
                Scenario.industry == "pest_control",
                Scenario.name == payload["name"],
            )
        )
        if scenario is None:
            scenario = Scenario(
                org_id=None,
                created_by_id=None,
                industry="pest_control",
                name=payload["name"],
                difficulty=payload["difficulty"],
                description=payload["description"],
                persona=payload["persona"],
                rubric=STANDARD_RUBRIC,
                stages=list(PHASE_ONE_STAGES),
            )
            db.add(scenario)
            continue

        scenario.difficulty = payload["difficulty"]
        scenario.description = payload["description"]
        scenario.persona = payload["persona"]
        scenario.rubric = STANDARD_RUBRIC
        scenario.stages = list(PHASE_ONE_STAGES)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        AnalyticsRefreshService().ensure_metric_definitions(db)
        _seed_prompt_versions(db)
        _seed_phase_one_scenarios(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
