from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.prompt_version import PromptVersion
from tests.test_grading_engine_v2 import _await_scorecard_and_run, _create_assignment, _run_session


def test_prompt_version_is_loaded_from_active_record(client, seed_org):
    db = SessionLocal()
    try:
        for row in db.scalars(select(PromptVersion).where(PromptVersion.prompt_type == "grading_v2")).all():
            row.active = False
        prompt = PromptVersion(
            prompt_type="grading_v2",
            version="1.1.0",
            content="Return valid JSON only. Use the grading v2 schema exactly.",
            active=True,
        )
        db.add(prompt)
        db.commit()
        db.refresh(prompt)
        prompt_id = prompt.id
    finally:
        db.close()

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can improve coverage, handle price concerns, and book a better plan today.",
    )

    _, grading_run = _await_scorecard_and_run(session_id)
    assert grading_run.prompt_version_id == prompt_id


def test_prompt_version_falls_back_to_seeded_default_when_none_active(client, seed_org):
    db = SessionLocal()
    try:
        default_prompt = db.scalar(
            select(PromptVersion).where(
                PromptVersion.prompt_type == "grading_v2",
                PromptVersion.version == "1.0.0",
            )
        )
        assert default_prompt is not None
        for row in db.scalars(select(PromptVersion).where(PromptVersion.prompt_type == "grading_v2")).all():
            row.active = False
        db.commit()
        default_prompt_id = default_prompt.id
    finally:
        db.close()

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I can walk you through the value, answer the objection, and schedule the service.",
    )

    _, grading_run = _await_scorecard_and_run(session_id)

    db = SessionLocal()
    try:
        refreshed_default = db.scalar(select(PromptVersion).where(PromptVersion.id == default_prompt_id))
        assert refreshed_default is not None
        assert refreshed_default.active is True
        assert refreshed_default.content
    finally:
        db.close()

    assert grading_run.prompt_version_id == default_prompt_id


def test_prompt_version_prefers_org_specific_active_record(client, seed_org):
    db = SessionLocal()
    try:
        for row in db.scalars(select(PromptVersion).where(PromptVersion.prompt_type == "grading_v2")).all():
            row.active = False
        global_prompt = PromptVersion(
            prompt_type="grading_v2",
            version="global_active",
            org_id=None,
            content="global grading prompt",
            active=True,
        )
        org_prompt = PromptVersion(
            prompt_type="grading_v2",
            version="org_active",
            org_id=seed_org["org_id"],
            content="org grading prompt",
            active=True,
        )
        db.add_all([global_prompt, org_prompt])
        db.commit()
        db.refresh(org_prompt)
        org_prompt_id = org_prompt.id
    finally:
        db.close()

    assignment = _create_assignment(client, seed_org)
    session_id = _run_session(
        client,
        seed_org,
        assignment["id"],
        "I handled the objection, explained the value, and asked for the next step.",
    )

    _, grading_run = _await_scorecard_and_run(session_id)
    assert grading_run.prompt_version_id == org_prompt_id
