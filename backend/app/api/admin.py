from __future__ import annotations

import base64
import json
import re
import uuid
import zlib
from datetime import date, datetime, time, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import Actor, require_manager
from app.db.seed_questionnaire import seed_questionnaire_questions
from app.db.session import get_db
from app.models.assignment import Assignment
from app.models.grading import GradingRun
from app.models.org_material import OrgKnowledgeDoc, OrgMaterial
from app.models.org_prompt_config import OrgPromptConfig
from app.models.postprocess_run import PostprocessRun
from app.models.prompt_version import PromptVersion
from app.models.questionnaire import OrgQuestionnaireResponse, QuestionnaireQuestion
from app.models.scenario import Scenario
from app.models.scorecard import Scorecard
from app.models.session import Session as DrillSession
from app.models.session import SessionArtifact, SessionEvent, SessionTurn
from app.models.training import AdaptiveRecommendationOutcome, ConversationQualitySignal, OverrideLabel, PromptExperiment
from app.models.types import SessionStatus, TurnSpeaker
from app.models.user import User
from app.services.conversation_realism_eval_service import ConversationRealismEvalService
from app.services.conversation_orchestrator import measure_prompt_tokens
from app.services.prompt_studio_service import PromptStudioService
from app.services.org_prompt_config_service import OrgPromptConfigService
from app.services.prompt_experiment_service import PromptExperimentService
from app.services.prompt_version_synthesizer import PromptVersionSynthesizer
from app.services.storage_service import StorageService
from app.tasks.material_tasks import enqueue_material_processing

router = APIRouter(prefix="/admin", tags=["admin"])
prompt_experiment_service = PromptExperimentService()
org_prompt_config_service = OrgPromptConfigService()
prompt_version_synthesizer = PromptVersionSynthesizer()
prompt_studio_service = PromptStudioService()
storage_service = StorageService()
conversation_realism_eval_service = ConversationRealismEvalService()
COMPANY_DOC_RE = re.compile(r"\[From: ([^\]]+)\]")


class PromptExperimentCreateRequest(BaseModel):
    prompt_type: str = Field(default="grading_v2")
    control_version_id: str
    challenger_version_id: str
    challenger_traffic_pct: int = Field(default=10, ge=0, le=100)
    min_sessions_for_decision: int = Field(default=200, ge=1)


class PromptVersionCreateRequest(BaseModel):
    prompt_type: str = Field(max_length=64)
    version: str = Field(max_length=64)
    org_id: str | None = Field(default=None)
    content: str = Field(min_length=1)
    active: bool = Field(default=False)


class PromptVersionUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    version: str | None = Field(default=None, max_length=64)


class QuestionnaireAnswerItem(BaseModel):
    question_key: str = Field(min_length=1, max_length=120)
    answer_value: Any


class KnowledgeDocApprovalRequest(BaseModel):
    approved: bool


def _to_start_of_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _to_end_of_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _turn_payload(turn: SessionTurn) -> dict:
    return {
        "id": turn.id,
        "turn_index": turn.turn_index,
        "speaker": turn.speaker.value,
        "stage": turn.stage,
        "text": turn.text,
        "raw_transcript_text": turn.raw_transcript_text,
        "normalized_transcript_text": turn.normalized_transcript_text,
        "transcript_provider": turn.transcript_provider,
        "transcript_confidence": turn.transcript_confidence,
        "started_at": turn.started_at.isoformat(),
        "ended_at": turn.ended_at.isoformat(),
        "objection_tags": list(turn.objection_tags or []),
        "emotion_before": turn.emotion_before,
        "emotion_after": turn.emotion_after,
        "emotion_changed": bool(turn.emotion_changed),
        "resistance_level": turn.resistance_level,
        "objection_pressure": turn.objection_pressure,
        "active_objections": list(turn.active_objections or []),
        "queued_objections": list(turn.queued_objections or []),
        "mb_tone": turn.mb_tone,
        "mb_sentence_length": turn.mb_sentence_length,
        "mb_behaviors": list(turn.mb_behaviors or []),
        "mb_interruption_type": turn.mb_interruption_type,
        "mb_realism_score": turn.mb_realism_score,
        "mb_opening_pause_ms": turn.mb_opening_pause_ms,
        "mb_total_pause_ms": turn.mb_total_pause_ms,
        "behavioral_signals": list(turn.behavioral_signals or []),
        "was_graded": bool(turn.was_graded),
        "evidence_for_categories": list(turn.evidence_for_categories or []),
        "is_high_quality": turn.is_high_quality,
    }


def _quality_filter(label_quality: str) -> set[str]:
    if label_quality == "high":
        return {"high"}
    if label_quality == "medium":
        return {"high", "medium"}
    return {"high", "medium", "low"}


def _decompress_prompt(text: str) -> str:
    return zlib.decompress(base64.b64decode(text.encode("ascii"))).decode("utf-8")


def _extract_company_doc_names(text: str | None) -> list[str]:
    if not text:
        return []

    seen: set[str] = set()
    names: list[str] = []
    for raw in COMPANY_DOC_RE.findall(text):
        name = str(raw).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _serialize_postprocess_run(run: PostprocessRun) -> dict:
    return {
        "status": run.status,
        "attempts": int(run.attempts),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "last_error": run.last_error,
    }


def _serialize_prompt_experiment(experiment: PromptExperiment, *, evaluation_summary: dict[str, Any] | None = None) -> dict:
    return {
        "id": experiment.id,
        "prompt_type": experiment.prompt_type,
        "control_version_id": experiment.control_version_id,
        "challenger_version_id": experiment.challenger_version_id,
        "challenger_traffic_pct": experiment.challenger_traffic_pct,
        "status": experiment.status,
        "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
        "ended_at": experiment.ended_at.isoformat() if experiment.ended_at else None,
        "winner": experiment.winner,
        "control_mean_calibration_error": experiment.control_mean_calibration_error,
        "challenger_mean_calibration_error": experiment.challenger_mean_calibration_error,
        "control_session_count": experiment.control_session_count,
        "challenger_session_count": experiment.challenger_session_count,
        "p_value": experiment.p_value,
        "min_sessions_for_decision": experiment.min_sessions_for_decision,
        "evaluation_summary": evaluation_summary,
    }


def _serialize_prompt_version(prompt_version: PromptVersion) -> dict:
    return {
        "id": prompt_version.id,
        "prompt_type": prompt_version.prompt_type,
        "version": prompt_version.version,
        "org_id": prompt_version.org_id,
        "content": prompt_version.content,
        "active": bool(prompt_version.active),
        "created_at": prompt_version.created_at.isoformat(),
        "updated_at": prompt_version.updated_at.isoformat(),
    }


def _serialize_org_prompt_config(config: OrgPromptConfig) -> dict:
    return {
        "id": config.id,
        "org_id": config.org_id,
        "company_name": config.company_name,
        "product_category": config.product_category,
        "product_description": config.product_description,
        "pitch_stages": list(config.pitch_stages or []),
        "unique_selling_points": list(config.unique_selling_points or []),
        "known_objections": list(config.known_objections or []),
        "target_demographics": dict(config.target_demographics or {}),
        "competitors": list(config.competitors or []),
        "pricing_framing": config.pricing_framing,
        "close_style": config.close_style,
        "rep_tone_guidance": config.rep_tone_guidance,
        "grading_priorities": list(config.grading_priorities or []),
        "published": bool(config.published),
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def _ensure_actor_can_access_org(actor: Actor, org_id: str) -> None:
    if actor.role != "admin" and actor.org_id is not None and actor.org_id != org_id:
        raise HTTPException(status_code=403, detail="cross-organization access denied")


def _ensure_actor_can_access_prompt_version(actor: Actor, prompt_version: PromptVersion) -> None:
    if actor.role == "admin" or actor.org_id is None:
        return
    if prompt_version.org_id is None or prompt_version.org_id == actor.org_id:
        return
    raise HTTPException(status_code=403, detail="cannot access prompt version outside your organization")


def _build_material_storage_key(org_id: str, filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "material")
    return f"org-materials/{org_id}/{uuid.uuid4().hex}/{safe_name}"


def _normalize_material_file_type(filename: str | None) -> str:
    extension = (filename or "").rsplit(".", 1)[-1].lower().strip()
    if extension in {"pdf", "docx", "txt", "csv"}:
        return extension
    if extension in {"mp4"}:
        return "video"
    if extension in {"mp3", "m4a"}:
        return "audio"
    raise HTTPException(status_code=400, detail="unsupported material file type")


def _serialize_org_material(material: OrgMaterial, db: Session) -> dict[str, Any]:
    structured_doc_count = db.scalar(
        select(func.count(OrgKnowledgeDoc.id))
        .where(
            OrgKnowledgeDoc.material_id == material.id,
            OrgKnowledgeDoc.extraction_type != "raw_chunk",
        )
    )
    return {
        "id": material.id,
        "org_id": material.org_id,
        "original_filename": material.original_filename,
        "file_type": material.file_type,
        "storage_key": material.storage_key,
        "file_size_bytes": material.file_size_bytes,
        "extraction_status": material.extraction_status,
        "extraction_error": material.extraction_error,
        "extracted_at": material.extracted_at.isoformat() if material.extracted_at else None,
        "created_at": material.created_at.isoformat() if material.created_at else None,
        "deleted_at": material.deleted_at.isoformat() if material.deleted_at else None,
        "structured_doc_count": int(structured_doc_count or 0),
    }


def _serialize_knowledge_doc(doc: OrgKnowledgeDoc) -> dict[str, Any]:
    return {
        "id": doc.id,
        "org_id": doc.org_id,
        "material_id": doc.material_id,
        "extraction_type": doc.extraction_type,
        "content": doc.content,
        "supporting_quote": doc.supporting_quote,
        "confidence": float(doc.confidence or 0.0),
        "manager_approved": doc.manager_approved,
        "used_in_config": bool(doc.used_in_config),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def _questionnaire_completion_summary(org_id: str, db: Session) -> dict[str, Any]:
    seed_questionnaire_questions(db)
    questions = db.scalars(
        select(QuestionnaireQuestion)
        .where(QuestionnaireQuestion.active.is_(True))
        .order_by(QuestionnaireQuestion.display_order.asc())
    ).all()
    responses = db.scalars(
        select(OrgQuestionnaireResponse).where(OrgQuestionnaireResponse.org_id == org_id)
    ).all()
    answered_ids = {response.question_id for response in responses}
    required_unanswered = [
        question.question_key
        for question in questions
        if question.required and question.id not in answered_ids
    ]
    total = len(questions)
    answered = sum(1 for question in questions if question.id in answered_ids)
    completion_pct = round((answered / total) * 100, 2) if total else 100.0
    return {
        "total_questions": total,
        "answered": answered,
        "required_unanswered": required_unanswered,
        "completion_pct": completion_pct,
    }


def _questionnaire_payload(org_id: str, db: Session) -> dict[str, Any]:
    seed_questionnaire_questions(db)
    questions = db.scalars(
        select(QuestionnaireQuestion)
        .where(QuestionnaireQuestion.active.is_(True))
        .order_by(QuestionnaireQuestion.category.asc(), QuestionnaireQuestion.display_order.asc())
    ).all()
    responses = db.scalars(
        select(OrgQuestionnaireResponse).where(OrgQuestionnaireResponse.org_id == org_id)
    ).all()
    response_by_question_id = {response.question_id: response for response in responses}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        response = response_by_question_id.get(question.id)
        grouped.setdefault(question.category, []).append(
            {
                "id": question.id,
                "question_key": question.question_key,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "options": question.options,
                "display_order": question.display_order,
                "category": question.category,
                "required": bool(question.required),
                "maps_to_config_field": question.maps_to_config_field,
                "answer_value": response.answer_value if response is not None else None,
                "answered_at": response.answered_at.isoformat() if response is not None and response.answered_at else None,
            }
        )

    return {
        "categories": grouped,
        **_questionnaire_completion_summary(org_id, db),
    }


@router.get("/prompt-versions")
def list_prompt_versions(
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
    prompt_type: str | None = Query(default=None),
    org_id: str | None = Query(default=None),
) -> list[dict]:
    stmt = select(PromptVersion)
    if prompt_type is not None:
        stmt = stmt.where(PromptVersion.prompt_type == prompt_type)
    if org_id is not None:
        _ensure_actor_can_access_org(actor, org_id)
        stmt = stmt.where(PromptVersion.org_id == org_id)
    elif actor.role != "admin" and actor.org_id is not None:
        stmt = stmt.where(or_(PromptVersion.org_id == actor.org_id, PromptVersion.org_id.is_(None)))
    prompt_versions = db.scalars(stmt.order_by(PromptVersion.created_at.desc())).all()
    return [_serialize_prompt_version(prompt_version) for prompt_version in prompt_versions]


@router.get("/prompt-versions/{version_id}")
def get_prompt_version(
    version_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    prompt_version = db.get(PromptVersion, version_id)
    if prompt_version is None:
        raise HTTPException(status_code=404, detail="prompt version not found")
    _ensure_actor_can_access_prompt_version(actor, prompt_version)
    return _serialize_prompt_version(prompt_version)


@router.post("/prompt-versions")
def create_prompt_version(
    payload: PromptVersionCreateRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    if payload.org_id is not None:
        _ensure_actor_can_access_org(actor, payload.org_id)
    existing = db.scalar(
        select(PromptVersion)
        .where(PromptVersion.prompt_type == payload.prompt_type)
        .where(PromptVersion.version == payload.version)
        .where(PromptVersion.org_id == payload.org_id if payload.org_id is not None else PromptVersion.org_id.is_(None))
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="prompt version already exists")

    prompt_version = PromptVersion(
        prompt_type=payload.prompt_type,
        version=payload.version,
        org_id=payload.org_id,
        content=payload.content,
        active=payload.active,
    )
    db.add(prompt_version)
    db.commit()
    db.refresh(prompt_version)
    return _serialize_prompt_version(prompt_version)


@router.patch("/prompt-versions/{version_id}")
def update_prompt_version(
    version_id: str,
    payload: PromptVersionUpdateRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    prompt_version = db.get(PromptVersion, version_id)
    if prompt_version is None:
        raise HTTPException(status_code=404, detail="prompt version not found")
    _ensure_actor_can_access_prompt_version(actor, prompt_version)

    if payload.version is not None and payload.version != prompt_version.version:
        existing = db.scalar(
            select(PromptVersion)
            .where(PromptVersion.prompt_type == prompt_version.prompt_type)
            .where(PromptVersion.version == payload.version)
            .where(
                PromptVersion.org_id == prompt_version.org_id
                if prompt_version.org_id is not None
                else PromptVersion.org_id.is_(None)
            )
            .where(PromptVersion.id != prompt_version.id)
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="prompt version already exists")
        prompt_version.version = payload.version
    if payload.content is not None:
        prompt_version.content = payload.content

    db.commit()
    db.refresh(prompt_version)
    return _serialize_prompt_version(prompt_version)


@router.post("/prompt-versions/{version_id}/activate")
def activate_prompt_version(
    version_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    prompt_version = db.get(PromptVersion, version_id)
    if prompt_version is None:
        raise HTTPException(status_code=404, detail="prompt version not found")
    _ensure_actor_can_access_prompt_version(actor, prompt_version)

    siblings_stmt = select(PromptVersion).where(PromptVersion.prompt_type == prompt_version.prompt_type)
    if prompt_version.org_id is None:
        siblings_stmt = siblings_stmt.where(PromptVersion.org_id.is_(None))
    else:
        siblings_stmt = siblings_stmt.where(PromptVersion.org_id == prompt_version.org_id)
    siblings = db.scalars(siblings_stmt).all()
    for sibling in siblings:
        sibling.active = sibling.id == prompt_version.id

    db.commit()
    db.refresh(prompt_version)
    return _serialize_prompt_version(prompt_version)


@router.get("/orgs/{org_id}/prompt-config")
def get_org_prompt_config(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    config = org_prompt_config_service.get_or_create_draft(org_id, db)
    db.commit()
    db.refresh(config)
    return _serialize_org_prompt_config(config)


@router.put("/orgs/{org_id}/prompt-config")
def update_org_prompt_config(
    org_id: str,
    payload: dict[str, Any],
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    try:
        config = org_prompt_config_service.update_config(org_id, payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(config)
    return _serialize_org_prompt_config(config)


@router.post("/orgs/{org_id}/prompt-config/publish")
def publish_org_prompt_config(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    config = org_prompt_config_service.publish_config(org_id, db)
    db.commit()
    db.refresh(config)

    prompt_rows = db.scalars(
        select(PromptVersion)
        .where(PromptVersion.org_id == org_id)
        .where(PromptVersion.active.is_(True))
        .where(PromptVersion.prompt_type.in_(("conversation", "grading_v2", "coaching")))
    ).all()
    prompt_versions: dict[str, dict] = {}
    for row in prompt_rows:
        key = "grading" if row.prompt_type == "grading_v2" else row.prompt_type
        prompt_versions[key] = _serialize_prompt_version(row)

    return {
        "config": _serialize_org_prompt_config(config),
        "prompt_versions": prompt_versions,
    }


@router.get("/orgs/{org_id}/prompt-config/preview")
def preview_org_prompt_config(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    config = db.scalar(select(OrgPromptConfig).where(OrgPromptConfig.org_id == org_id))
    if config is None:
        config = OrgPromptConfig(
            org_id=org_id,
            company_name="",
            product_category="",
            product_description=None,
            pitch_stages=[],
            unique_selling_points=[],
            known_objections=[],
            target_demographics={},
            competitors=[],
            pricing_framing=None,
            close_style=None,
            rep_tone_guidance=None,
            grading_priorities=[],
            published=False,
        )
    preview = prompt_version_synthesizer.build_preview(config)
    return {
        "config": _serialize_org_prompt_config(config),
        **preview,
    }


@router.post("/orgs/{org_id}/materials")
async def upload_org_material(
    org_id: str,
    file: UploadFile = File(...),
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    file_type = _normalize_material_file_type(file.filename)
    max_size = 100 * 1024 * 1024
    file_bytes = await file.read(max_size + 1)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=413, detail="file too large, max 100MB")

    storage_key = _build_material_storage_key(org_id, file.filename or f"material.{file_type}")
    storage_service.upload_bytes(storage_key, file_bytes, content_type=file.content_type or "application/octet-stream")

    material = OrgMaterial(
        org_id=org_id,
        original_filename=file.filename or f"material.{file_type}",
        file_type=file_type,
        storage_key=storage_key,
        file_size_bytes=len(file_bytes),
        extraction_status="pending",
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    enqueue_material_processing(material.id)
    return {"material_id": material.id, "extraction_status": material.extraction_status}


@router.get("/orgs/{org_id}/materials")
def list_org_materials(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> list[dict]:
    _ensure_actor_can_access_org(actor, org_id)
    materials = db.scalars(
        select(OrgMaterial)
        .where(OrgMaterial.org_id == org_id, OrgMaterial.deleted_at.is_(None))
        .order_by(OrgMaterial.created_at.desc(), OrgMaterial.id.desc())
    ).all()
    return [_serialize_org_material(material, db) for material in materials]


@router.get("/orgs/{org_id}/materials/{material_id}/status")
def get_org_material_status(
    org_id: str,
    material_id: int,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    material = db.scalar(
        select(OrgMaterial).where(
            OrgMaterial.id == material_id,
            OrgMaterial.org_id == org_id,
        )
    )
    if material is None or material.deleted_at is not None:
        raise HTTPException(status_code=404, detail="material not found")
    extracted_doc_count = db.scalar(
        select(func.count(OrgKnowledgeDoc.id)).where(
            OrgKnowledgeDoc.material_id == material.id,
            OrgKnowledgeDoc.extraction_type != "raw_chunk",
        )
    )
    return {
        "material_id": material.id,
        "extraction_status": material.extraction_status,
        "extracted_doc_count": int(extracted_doc_count or 0),
        "extraction_error": material.extraction_error,
    }


@router.delete("/orgs/{org_id}/materials/{material_id}")
def delete_org_material(
    org_id: str,
    material_id: int,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    material = db.scalar(
        select(OrgMaterial).where(
            OrgMaterial.id == material_id,
            OrgMaterial.org_id == org_id,
        )
    )
    if material is None or material.deleted_at is not None:
        raise HTTPException(status_code=404, detail="material not found")
    material.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "material_id": material.id}


@router.get("/orgs/{org_id}/questionnaire")
def get_org_questionnaire(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    return _questionnaire_payload(org_id, db)


@router.post("/orgs/{org_id}/questionnaire/answers")
def upsert_org_questionnaire_answers(
    org_id: str,
    payload: list[QuestionnaireAnswerItem],
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    seed_questionnaire_questions(db)
    questions = db.scalars(select(QuestionnaireQuestion).where(QuestionnaireQuestion.active.is_(True))).all()
    question_by_key = {question.question_key: question for question in questions}

    draft_updates: dict[str, Any] = {}
    for item in payload:
        question = question_by_key.get(item.question_key)
        if question is None:
            raise HTTPException(status_code=400, detail=f"unknown question_key: {item.question_key}")
        serialized_answer = (
            json.dumps(item.answer_value, ensure_ascii=True)
            if question.question_type == "multi_choice"
            else str(item.answer_value or "").strip()
        )
        existing = db.scalar(
            select(OrgQuestionnaireResponse).where(
                OrgQuestionnaireResponse.org_id == org_id,
                OrgQuestionnaireResponse.question_id == question.id,
            )
        )
        if existing is None:
            existing = OrgQuestionnaireResponse(
                org_id=org_id,
                question_id=question.id,
                answer_value=serialized_answer,
            )
            db.add(existing)
        else:
            existing.answer_value = serialized_answer
            existing.answered_at = datetime.now(timezone.utc)
        if question.maps_to_config_field:
            draft_updates[question.maps_to_config_field] = item.answer_value

    db.commit()
    if draft_updates:
        try:
            prompt_studio_service.update_draft_fields(org_id, draft_updates, db)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _questionnaire_completion_summary(org_id, db)


@router.get("/orgs/{org_id}/questionnaire/completion")
def get_org_questionnaire_completion(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    return _questionnaire_completion_summary(org_id, db)


@router.post("/orgs/{org_id}/prompt-studio/generate")
def generate_prompt_studio_draft(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    completion = _questionnaire_completion_summary(org_id, db)
    completed_material_count = db.scalar(
        select(func.count(OrgMaterial.id)).where(
            OrgMaterial.org_id == org_id,
            OrgMaterial.deleted_at.is_(None),
            OrgMaterial.extraction_status == "complete",
        )
    )
    missing: list[str] = []
    if int(completed_material_count or 0) < 1:
        missing.append("at least one extracted material")
    if float(completion["completion_pct"]) <= 80.0:
        missing.append("questionnaire completion must be above 80%")
    if missing:
        raise HTTPException(status_code=400, detail={"missing_requirements": missing, **completion})
    config = prompt_studio_service.generate_draft_config(org_id, db)
    return _serialize_org_prompt_config(config)


@router.get("/orgs/{org_id}/prompt-studio/preview")
def preview_prompt_studio_draft(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    return prompt_studio_service.get_draft_preview(org_id, db)


@router.get("/orgs/{org_id}/prompt-studio/knowledge-docs")
def get_prompt_studio_knowledge_docs(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
    approved: str | None = Query(default=None),
    type: str | None = Query(default=None),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    stmt = (
        select(OrgKnowledgeDoc)
        .join(OrgMaterial, OrgMaterial.id == OrgKnowledgeDoc.material_id)
        .where(
            OrgKnowledgeDoc.org_id == org_id,
            OrgKnowledgeDoc.extraction_type != "raw_chunk",
            OrgMaterial.deleted_at.is_(None),
        )
        .order_by(OrgKnowledgeDoc.extraction_type.asc(), OrgKnowledgeDoc.confidence.asc(), OrgKnowledgeDoc.id.asc())
    )
    if approved == "true":
        stmt = stmt.where(OrgKnowledgeDoc.manager_approved.is_(True))
    elif approved == "false":
        stmt = stmt.where(OrgKnowledgeDoc.manager_approved.is_(False))
    elif approved == "null":
        stmt = stmt.where(OrgKnowledgeDoc.manager_approved.is_(None))
    if type:
        stmt = stmt.where(OrgKnowledgeDoc.extraction_type == type)

    docs = db.scalars(stmt).all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        grouped.setdefault(doc.extraction_type, []).append(_serialize_knowledge_doc(doc))
    return {"groups": grouped}


@router.patch("/orgs/{org_id}/prompt-studio/knowledge-docs/{doc_id}")
def approve_prompt_studio_knowledge_doc(
    org_id: str,
    doc_id: int,
    payload: KnowledgeDocApprovalRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    doc = db.get(OrgKnowledgeDoc, doc_id)
    if doc is None or doc.org_id != org_id:
        raise HTTPException(status_code=404, detail="knowledge doc not found")
    try:
        prompt_studio_service.approve_knowledge_doc(doc_id, payload.approved, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.refresh(doc)
    return _serialize_knowledge_doc(doc)


@router.patch("/orgs/{org_id}/prompt-studio/config")
def patch_prompt_studio_config(
    org_id: str,
    payload: dict[str, Any],
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    try:
        config = prompt_studio_service.update_draft_fields(org_id, payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_org_prompt_config(config)


@router.post("/orgs/{org_id}/prompt-studio/regenerate")
def regenerate_prompt_studio_draft(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    config = prompt_studio_service.generate_draft_config(org_id, db)
    return _serialize_org_prompt_config(config)


@router.post("/orgs/{org_id}/prompt-studio/publish")
def publish_prompt_studio_draft(
    org_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_actor_can_access_org(actor, org_id)
    config = org_prompt_config_service.publish_config(org_id, db)
    preview = prompt_studio_service.get_draft_preview(org_id, db)
    docs = db.scalars(
        select(OrgKnowledgeDoc).where(
            OrgKnowledgeDoc.org_id == org_id,
            OrgKnowledgeDoc.extraction_type != "raw_chunk",
        )
    ).all()
    for doc in docs:
        doc.used_in_config = bool(doc.manager_approved)
    db.commit()
    prompt_versions = {
        key: _serialize_prompt_version(value)
        for key, value in prompt_version_synthesizer.get_active_versions_for_org(org_id, db).items()
    }
    return {
        "published_at": config.updated_at.isoformat() if config.updated_at else None,
        "prompt_versions": prompt_versions,
        "system_prompt_token_count": preview["system_prompt_token_count"],
    }


@router.post("/prompt-experiments")
def create_prompt_experiment(
    payload: PromptExperimentCreateRequest,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    control = db.get(PromptVersion, payload.control_version_id)
    challenger = db.get(PromptVersion, payload.challenger_version_id)
    if control is None or challenger is None:
        raise HTTPException(status_code=404, detail="prompt version not found")
    _ensure_actor_can_access_prompt_version(actor, control)
    _ensure_actor_can_access_prompt_version(actor, challenger)
    if control.prompt_type != payload.prompt_type or challenger.prompt_type != payload.prompt_type:
        raise HTTPException(status_code=400, detail="prompt versions must match prompt_type")
    if control.org_id != challenger.org_id:
        raise HTTPException(status_code=400, detail="prompt versions must share the same org scope")

    experiment = prompt_experiment_service.create_experiment(
        db,
        prompt_type=payload.prompt_type,
        control_version_id=payload.control_version_id,
        challenger_version_id=payload.challenger_version_id,
        challenger_traffic_pct=payload.challenger_traffic_pct,
        min_sessions_for_decision=payload.min_sessions_for_decision,
    )
    db.commit()
    db.refresh(experiment)
    return _serialize_prompt_experiment(experiment, evaluation_summary=prompt_experiment_service.build_evaluation_summary(db, experiment))


@router.get("/prompt-experiments/{experiment_id}")
def get_prompt_experiment(
    experiment_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    experiment = db.get(PromptExperiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="prompt experiment not found")
    return _serialize_prompt_experiment(experiment, evaluation_summary=prompt_experiment_service.build_evaluation_summary(db, experiment))


@router.post("/prompt-experiments/{experiment_id}/evaluate")
def evaluate_prompt_experiment(
    experiment_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    try:
        experiment = prompt_experiment_service.evaluate(db, experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    db.refresh(experiment)
    return _serialize_prompt_experiment(experiment, evaluation_summary=prompt_experiment_service.build_evaluation_summary(db, experiment))


@router.post("/prompt-experiments/{experiment_id}/promote")
def promote_prompt_experiment_winner(
    experiment_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    try:
        experiment = prompt_experiment_service.promote_winner(db, experiment_id)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    db.commit()
    db.refresh(experiment)
    return _serialize_prompt_experiment(experiment, evaluation_summary=prompt_experiment_service.build_evaluation_summary(db, experiment))


@router.get("/sessions/{session_id}/training-loop-audit")
def get_training_loop_audit(
    session_id: str,
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
) -> dict:
    session = db.scalar(select(DrillSession).where(DrillSession.id == session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    rep = db.scalar(select(User).where(User.id == session.rep_id))
    if actor.role != "admin" and actor.org_id is not None and rep is not None and rep.org_id != actor.org_id:
        raise HTTPException(status_code=403, detail="cannot access session outside your organization")

    assignment = db.scalar(select(Assignment).where(Assignment.id == session.assignment_id))
    scorecard = db.scalar(select(Scorecard).where(Scorecard.session_id == session_id))
    artifacts = db.scalars(select(SessionArtifact).where(SessionArtifact.session_id == session_id)).all()
    postprocess_runs = db.scalars(
        select(PostprocessRun)
        .where(PostprocessRun.session_id == session_id)
        .order_by(PostprocessRun.task_type.asc())
    ).all()
    latest_ai_turn = db.scalar(
        select(SessionTurn)
        .where(
            SessionTurn.session_id == session_id,
            SessionTurn.speaker == TurnSpeaker.AI,
            SessionTurn.system_prompt_snapshot.is_not(None),
        )
        .order_by(SessionTurn.turn_index.desc())
    )
    latest_grading_run = db.scalar(
        select(GradingRun)
        .where(GradingRun.session_id == session_id)
        .order_by(GradingRun.completed_at.desc(), GradingRun.created_at.desc())
    )
    adaptive_outcome = db.scalar(
        select(AdaptiveRecommendationOutcome)
        .where(AdaptiveRecommendationOutcome.assignment_id == session.assignment_id)
        .order_by(AdaptiveRecommendationOutcome.created_at.desc())
    )

    latest_prompt = None
    prompt_doc_names: list[str] = []
    if latest_ai_turn is not None and latest_ai_turn.system_prompt_snapshot:
        latest_prompt = _decompress_prompt(latest_ai_turn.system_prompt_snapshot)
        prompt_doc_names = _extract_company_doc_names(latest_prompt)

    grading_text = latest_grading_run.raw_llm_response if latest_grading_run is not None else None
    grading_doc_names = _extract_company_doc_names(grading_text)

    adaptive_metadata: dict = {}
    if assignment is not None and isinstance(assignment.retry_policy, dict):
        maybe_metadata = assignment.retry_policy.get("adaptive_training")
        if isinstance(maybe_metadata, dict):
            adaptive_metadata = maybe_metadata

    transcript_artifacts = [artifact for artifact in artifacts if artifact.artifact_type == "canonical_transcript"]
    audio_artifacts = [artifact for artifact in artifacts if artifact.artifact_type == "audio"]

    return {
        "session": {
            "id": session.id,
            "assignment_id": session.assignment_id,
            "rep_id": session.rep_id,
            "scenario_id": session.scenario_id,
            "status": session.status.value if isinstance(session.status, SessionStatus) else str(session.status),
            "prompt_version": session.prompt_version,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        },
        "finalization": {
            "transcript_artifact_present": bool(transcript_artifacts),
            "transcript_artifact_count": len(transcript_artifacts),
            "audio_artifact_count": len(audio_artifacts),
            "scorecard_present": scorecard is not None,
            "latest_grading_run_status": latest_grading_run.status if latest_grading_run is not None else None,
            "postprocess_runs": {
                run.task_type: _serialize_postprocess_run(run)
                for run in postprocess_runs
            },
        },
        "prompt_audit": {
            "has_prompt_snapshot": latest_prompt is not None,
            "turn_id": latest_ai_turn.id if latest_ai_turn is not None else None,
            "turn_index": latest_ai_turn.turn_index if latest_ai_turn is not None else None,
            "has_company_context": bool(latest_prompt and "LAYER 5 - WHAT YOU MAY KNOW ABOUT THIS COMPANY" in latest_prompt),
            "company_doc_names": prompt_doc_names,
            "has_behavior_directives": bool(latest_prompt and "LAYER 3C - BEHAVIORAL DIRECTIVES" in latest_prompt),
            "has_prior_turn_register": bool(latest_prompt and "LAYER 3B-CONT - PRIOR TURN REGISTER" in latest_prompt),
            "prompt_token_count": measure_prompt_tokens(latest_prompt or "") if latest_prompt is not None else None,
        },
        "grading_audit": {
            "grading_run_id": latest_grading_run.id if latest_grading_run is not None else None,
            "grading_run_status": latest_grading_run.status if latest_grading_run is not None else None,
            "prompt_version_id": latest_grading_run.prompt_version_id if latest_grading_run is not None else None,
            "prompt_version": latest_grading_run.prompt_version.version if latest_grading_run is not None else None,
            "raw_llm_response_present": bool(grading_text),
            "has_company_training_material": bool(grading_text and "=== Company Training Material ===" in grading_text),
            "company_doc_names": grading_doc_names,
        },
        "adaptive_audit": {
            "has_adaptive_metadata": bool(adaptive_metadata),
            "focus_skills": [
                str(skill)
                for skill in adaptive_metadata.get("recommended_focus_skills", [])
                if isinstance(skill, str) and skill
            ],
            "baseline_skill_scores_present": bool(adaptive_metadata.get("baseline_skill_scores")),
            "outcome_present": adaptive_outcome is not None,
            "outcome_written_at": (
                adaptive_outcome.outcome_written_at.isoformat()
                if adaptive_outcome is not None and adaptive_outcome.outcome_written_at
                else None
            ),
            "skill_delta_present": bool(adaptive_outcome is not None and adaptive_outcome.skill_delta),
        },
    }


@router.get("/training-signals/export")
def export_training_signals(
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
    quality: Literal["high", "medium", "all"] = Query(default="all"),
    prompt_type: str = Query(default="grading_v2"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    format: Literal["jsonl", "json"] = Query(default="jsonl"),
) -> Response:
    batch_id = str(uuid.uuid4())
    allowed_qualities = _quality_filter(quality)
    start_at = _to_start_of_day(from_date)
    end_at = _to_end_of_day(to_date)

    stmt = (
        select(OverrideLabel, GradingRun, PromptVersion, DrillSession, Scorecard, Scenario)
        .join(GradingRun, GradingRun.id == OverrideLabel.grading_run_id)
        .join(PromptVersion, PromptVersion.id == GradingRun.prompt_version_id)
        .join(DrillSession, DrillSession.id == OverrideLabel.session_id)
        .join(Scorecard, Scorecard.session_id == DrillSession.id)
        .outerjoin(Scenario, Scenario.id == DrillSession.scenario_id)
        .where(PromptVersion.prompt_type == prompt_type)
    )
    if actor.org_id is not None:
        stmt = stmt.where(OverrideLabel.org_id == actor.org_id)
    if quality != "all":
        stmt = stmt.where(OverrideLabel.label_quality.in_(allowed_qualities))
    if start_at is not None:
        stmt = stmt.where(OverrideLabel.created_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(OverrideLabel.created_at <= end_at)

    rows = db.execute(stmt.order_by(OverrideLabel.created_at.asc())).all()
    session_ids = [row.OverrideLabel.session_id for row in rows]
    turns_by_session: dict[str, list[SessionTurn]] = {}
    if session_ids:
        turn_rows = db.scalars(
            select(SessionTurn)
            .where(SessionTurn.session_id.in_(session_ids))
            .order_by(SessionTurn.session_id.asc(), SessionTurn.turn_index.asc())
        ).all()
        for turn in turn_rows:
            turns_by_session.setdefault(turn.session_id, []).append(turn)

    examples: list[dict] = []
    exported_at = datetime.now(timezone.utc)
    for row in rows:
        label, grading_run, prompt_version_row, session, scorecard, scenario = row

        label.exported_at = exported_at
        label.export_batch_id = batch_id

        examples.append(
            {
                "input": {
                    "session_id": session.id,
                    "transcript": [_turn_payload(turn) for turn in turns_by_session.get(session.id, [])],
                    "prompt_version": prompt_version_row.version,
                    "scenario": (
                        {
                            "id": scenario.id,
                            "name": scenario.name,
                            "industry": scenario.industry,
                            "difficulty": scenario.difficulty,
                            "description": scenario.description,
                            "stages": list(scenario.stages or []),
                        }
                        if scenario is not None
                        else None
                    ),
                },
                "ai_output": {
                    "overall_score": label.ai_overall_score,
                    "category_scores": label.ai_category_scores,
                    "ai_summary": scorecard.ai_summary,
                    "grading_run_id": grading_run.id,
                },
                "human_correction": {
                    "override_overall_score": label.override_overall_score,
                    "override_category_scores": label.override_category_scores,
                    "delta": label.override_delta_overall,
                    "manager_id": label.manager_id,
                    "label_quality": label.label_quality,
                    "reason_text": label.override_reason_text,
                },
            }
        )

    db.commit()

    if format == "json":
        return Response(content=json.dumps(examples, ensure_ascii=True), media_type="application/json")

    body = "\n".join(json.dumps(item, ensure_ascii=True) for item in examples)
    return Response(content=body, media_type="application/x-ndjson")


@router.get("/training-signals/conversation-export")
def export_conversation_training_signals(
    actor: Actor = Depends(require_manager),
    db: Session = Depends(get_db),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    min_realism_score: float | None = Query(default=None),
    min_transcript_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    min_manager_realism_rating: int | None = Query(default=None, ge=1, le=5),
    min_eval_score: float | None = Query(default=None, ge=0.0, le=10.0),
    bucket: Literal["all", "high_value", "repetition", "over_softening", "missed_objection", "transcript_corruption"] = Query(default="all"),
    quality_signal_only: bool = Query(default=False),
    format: Literal["jsonl", "json"] = Query(default="jsonl"),
) -> Response:
    batch_id = str(uuid.uuid4())
    start_at = _to_start_of_day(from_date)
    end_at = _to_end_of_day(to_date)

    stmt = (
        select(DrillSession, Scenario, User)
        .join(User, User.id == DrillSession.rep_id)
        .outerjoin(Scenario, Scenario.id == DrillSession.scenario_id)
        .where(DrillSession.status == SessionStatus.GRADED)
    )
    if actor.org_id is not None:
        stmt = stmt.where(User.org_id == actor.org_id)
    if start_at is not None:
        stmt = stmt.where(DrillSession.started_at >= start_at)
    if end_at is not None:
        stmt = stmt.where(DrillSession.started_at <= end_at)

    session_rows = db.execute(stmt.order_by(DrillSession.started_at.asc())).all()
    session_ids = [session.id for session, _, _ in session_rows]
    turns_by_session: dict[str, list[SessionTurn]] = {}
    if session_ids:
        turn_rows = db.scalars(
            select(SessionTurn)
            .where(SessionTurn.session_id.in_(session_ids))
            .order_by(SessionTurn.session_id.asc(), SessionTurn.turn_index.asc())
        ).all()
        for turn in turn_rows:
            turns_by_session.setdefault(turn.session_id, []).append(turn)
    committed_payloads_by_session: dict[str, list[dict[str, Any]]] = {}
    if session_ids:
        committed_events = db.scalars(
            select(SessionEvent)
            .where(
                SessionEvent.session_id.in_(session_ids),
                SessionEvent.event_type == "server.turn.committed",
            )
            .order_by(SessionEvent.session_id.asc(), SessionEvent.event_ts.asc())
        ).all()
        for event in committed_events:
            committed_payloads_by_session.setdefault(event.session_id, []).append(dict(event.payload or {}))

    quality_signals_by_session: dict[str, ConversationQualitySignal] = {}
    if session_ids:
        quality_signal_rows = db.scalars(
            select(ConversationQualitySignal)
            .where(ConversationQualitySignal.session_id.in_(session_ids))
            .order_by(ConversationQualitySignal.session_id.asc(), ConversationQualitySignal.created_at.desc())
        ).all()
        for signal in quality_signal_rows:
            quality_signals_by_session.setdefault(signal.session_id, signal)

    examples: list[dict] = []
    exported_at = datetime.now(timezone.utc)
    updated_signal_ids: set[str] = set()
    for session, scenario, rep in session_rows:
        quality_signal = quality_signals_by_session.get(session.id)
        if quality_signal_only and quality_signal is None:
            continue
        if min_manager_realism_rating is not None and (
            quality_signal is None or quality_signal.realism_rating is None or quality_signal.realism_rating < min_manager_realism_rating
        ):
            continue

        turns = turns_by_session.get(session.id, [])
        session_eval = conversation_realism_eval_service.evaluate_session(
            turns=turns,
            committed_payloads=committed_payloads_by_session.get(session.id, []),
            quality_signal=quality_signal,
        )
        if min_eval_score is not None and session_eval.overall_score < min_eval_score:
            continue
        if bucket != "all":
            if bucket == "high_value":
                transcript_floor = min_transcript_confidence if min_transcript_confidence is not None else 0.85
                manager_ok = quality_signal is not None and (quality_signal.realism_rating or 0) >= 4
                eval_ok = session_eval.overall_score >= (min_eval_score if min_eval_score is not None else 8.0)
                if not manager_ok and not eval_ok:
                    continue
                if session_eval.failure_labels:
                    continue
                if not any(
                    (turn.transcript_confidence or 0.0) >= transcript_floor
                    for turn in turns
                    if turn.speaker == TurnSpeaker.REP
                ):
                    continue
            elif bucket not in set(session_eval.failure_labels):
                continue

        for index, turn in enumerate(turns):
            if turn.speaker != TurnSpeaker.AI or turn.system_prompt_snapshot is None:
                continue
            if min_realism_score is not None and (
                turn.mb_realism_score is None or float(turn.mb_realism_score) < float(min_realism_score)
            ):
                continue
            previous_turn = turns[index - 1] if index > 0 else None
            if (
                min_transcript_confidence is not None
                and previous_turn is not None
                and previous_turn.speaker == TurnSpeaker.REP
                and (previous_turn.transcript_confidence or 0.0) < min_transcript_confidence
            ):
                continue

            if quality_signal is not None and quality_signal.id not in updated_signal_ids:
                quality_signal.exported_at = exported_at
                quality_signal.export_batch_id = batch_id
                updated_signal_ids.add(quality_signal.id)

            examples.append(
                {
                    "session_id": session.id,
                    "turn_id": turn.id,
                    "turn_index": turn.turn_index,
                    "input": {
                        "system_prompt": _decompress_prompt(turn.system_prompt_snapshot),
                        "conversation_history": [
                            {
                                "speaker": previous_turn.speaker.value,
                                "text": previous_turn.text,
                            }
                            for previous_turn in turns[:index]
                        ],
                    },
                    "output": {
                        "text": turn.text,
                        "emotion_before": turn.emotion_before,
                        "emotion_after": turn.emotion_after,
                        "stage": turn.stage,
                    },
                    "signals": {
                        "mb_realism_score": turn.mb_realism_score,
                        "mb_tone": turn.mb_tone,
                        "mb_behaviors": list(turn.mb_behaviors or []),
                        "was_graded": bool(turn.was_graded),
                        "is_high_quality": turn.is_high_quality,
                        "manager_realism_rating": quality_signal.realism_rating if quality_signal is not None else None,
                        "manager_flagged": bool(
                            quality_signal is not None and turn.id in (quality_signal.flagged_turn_ids or [])
                        ),
                        "session_eval_overall_score": session_eval.overall_score,
                        "session_eval_failure_labels": list(session_eval.failure_labels),
                        "transcript_confidence": (
                            previous_turn.transcript_confidence
                            if previous_turn is not None and previous_turn.speaker == TurnSpeaker.REP
                            else None
                        ),
                    },
                    "metadata": {
                        "scenario_id": session.scenario_id,
                        "scenario_name": scenario.name if scenario is not None else None,
                        "scenario_difficulty": scenario.difficulty if scenario is not None else None,
                        "prompt_version": session.prompt_version,
                        "org_id": rep.org_id,
                        "session_date": session.started_at.date().isoformat() if session.started_at is not None else None,
                        "export_bucket": bucket,
                        "session_eval": session_eval.to_payload(),
                    },
                }
            )

    db.commit()

    if format == "json":
        return Response(content=json.dumps(examples, ensure_ascii=True), media_type="application/json")

    body = "\n".join(json.dumps(item, ensure_ascii=True) for item in examples)
    return Response(content=body, media_type="application/x-ndjson")
