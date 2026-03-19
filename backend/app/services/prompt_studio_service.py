from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.seed_questionnaire import seed_questionnaire_questions
from app.models.org_material import OrgKnowledgeDoc, OrgMaterial
from app.models.org_prompt_config import OrgPromptConfig
from app.models.questionnaire import OrgQuestionnaireResponse, QuestionnaireQuestion
from app.models.user import Organization
from app.services.conversation_orchestrator import measure_prompt_tokens
from app.services.org_prompt_config_service import OrgPromptConfigService
from app.services.org_prompt_rendering import build_company_context_layer
from app.services.prompt_version_synthesizer import PromptVersionSynthesizer

LINE_SPLIT_RE = re.compile(r"[\n\r]+|(?<!\d)[;•]")


class PromptStudioService:
    def __init__(self) -> None:
        self.org_prompt_config_service = OrgPromptConfigService()
        self.synthesizer = PromptVersionSynthesizer()

    def generate_draft_config(self, org_id: str, db: Session) -> OrgPromptConfig:
        seed_questionnaire_questions(db)
        draft = self.org_prompt_config_service.get_or_create_draft(org_id, db)
        updates, _docs = self._build_draft_updates(org_id, draft, db)
        for field, value in updates.items():
            setattr(draft, field, value)
        draft.published = False
        db.commit()
        db.refresh(draft)
        self.org_prompt_config_service.invalidate_cache(org_id)
        return draft

    def _synthesize_field(
        self,
        field_name: str,
        extracted_docs: list[OrgKnowledgeDoc],
        questionnaire_answer: str | list[str] | None,
    ) -> Any:
        if field_name == "known_objections":
            objections = self._dedupe_strings(
                [doc.content for doc in extracted_docs if doc.extraction_type == "objection"]
            )
            rebuttals = self._dedupe_strings(
                [doc.content for doc in extracted_docs if doc.extraction_type == "rebuttal"]
            )
            rows: list[dict[str, str | None]] = []
            for line in self._parse_lines(questionnaire_answer):
                objection, hint = self._split_objection_hint(line)
                if objection:
                    rows.append(
                        {
                            "objection": objection,
                            "preferred_rebuttal_hint": hint,
                        }
                    )
            for index, objection in enumerate(objections):
                rows.append(
                    {
                        "objection": objection,
                        "preferred_rebuttal_hint": rebuttals[index] if index < len(rebuttals) else None,
                    }
                )
            return self._dedupe_object_rows(rows, key="objection")

        if field_name == "unique_selling_points":
            merged = self._parse_lines(questionnaire_answer) + [
                doc.content for doc in extracted_docs if doc.extraction_type == "usp"
            ]
            return self._dedupe_strings(merged)

        if field_name == "competitors":
            rows: list[dict[str, str | None]] = []
            for line in self._parse_lines(questionnaire_answer):
                name, differentiator = self._split_named_value(line)
                if name:
                    rows.append({"name": name, "key_differentiator": differentiator})
            for doc in extracted_docs:
                if doc.extraction_type != "competitor":
                    continue
                name, differentiator = self._split_named_value(doc.content)
                rows.append({"name": name or doc.content, "key_differentiator": differentiator})
            return self._dedupe_object_rows(rows, key="name")

        return questionnaire_answer

    def get_draft_preview(self, org_id: str, db: Session) -> dict:
        seed_questionnaire_questions(db)
        draft = self.org_prompt_config_service.get_or_create_draft(org_id, db)
        updates, docs = self._build_draft_updates(org_id, draft, db)
        preview_config = OrgPromptConfig(
            id=draft.id,
            org_id=org_id,
            company_name=updates.get("company_name", draft.company_name),
            product_category=updates.get("product_category", draft.product_category),
            product_description=updates.get("product_description", draft.product_description),
            pitch_stages=updates.get("pitch_stages", draft.pitch_stages),
            unique_selling_points=updates.get("unique_selling_points", draft.unique_selling_points),
            known_objections=updates.get("known_objections", draft.known_objections),
            target_demographics=updates.get("target_demographics", draft.target_demographics),
            competitors=updates.get("competitors", draft.competitors),
            pricing_framing=updates.get("pricing_framing", draft.pricing_framing),
            close_style=updates.get("close_style", draft.close_style),
            rep_tone_guidance=updates.get("rep_tone_guidance", draft.rep_tone_guidance),
            grading_priorities=updates.get("grading_priorities", draft.grading_priorities),
            published=False,
        )
        rendered = self.synthesizer.render_for_org(preview_config)
        layer_zero = build_company_context_layer(preview_config, require_published=False)
        token_count = measure_prompt_tokens("\n\n".join(part for part in (layer_zero or "", rendered["conversation"]) if part))

        return {
            "layer_0_preview": layer_zero,
            "conversation_prompt": rendered["conversation"],
            "grading_prompt": rendered["grading"],
            "coaching_prompt": rendered["coaching"],
            "system_prompt_token_count": token_count,
            "knowledge_docs_used": len(docs),
            "low_confidence_items": [
                self._serialize_doc(doc)
                for doc in docs
                if float(doc.confidence or 0.0) < 0.75
            ],
        }

    def get_knowledge_docs_for_review(self, org_id: str, db: Session) -> list[OrgKnowledgeDoc]:
        return db.scalars(
            select(OrgKnowledgeDoc)
            .join(OrgMaterial, OrgMaterial.id == OrgKnowledgeDoc.material_id)
            .where(
                OrgKnowledgeDoc.org_id == org_id,
                OrgKnowledgeDoc.extraction_type != "raw_chunk",
                OrgKnowledgeDoc.manager_approved.is_(None),
                OrgMaterial.deleted_at.is_(None),
            )
            .order_by(OrgKnowledgeDoc.confidence.asc(), OrgKnowledgeDoc.created_at.asc())
        ).all()

    def approve_knowledge_doc(self, doc_id: int, approved: bool, db: Session) -> None:
        doc = db.get(OrgKnowledgeDoc, doc_id)
        if doc is None:
            raise ValueError("knowledge doc not found")
        doc.manager_approved = approved
        db.commit()

    def update_draft_field(self, org_id: str, field: str, value: Any, db: Session) -> OrgPromptConfig:
        valid_fields = self._editable_config_fields()
        if field not in valid_fields:
            raise ValueError(f"invalid config field: {field}")
        draft = self.org_prompt_config_service.get_or_create_draft(org_id, db)
        setattr(draft, field, value)
        draft.published = False
        db.commit()
        db.refresh(draft)
        self.org_prompt_config_service.invalidate_cache(org_id)
        return draft

    def update_draft_fields(self, org_id: str, updates: dict[str, Any], db: Session) -> OrgPromptConfig:
        draft = self.org_prompt_config_service.get_or_create_draft(org_id, db)
        valid_fields = self._editable_config_fields()
        for field, value in updates.items():
            if field not in valid_fields:
                raise ValueError(f"invalid config field: {field}")
            setattr(draft, field, value)
        draft.published = False
        db.commit()
        db.refresh(draft)
        self.org_prompt_config_service.invalidate_cache(org_id)
        return draft

    def _build_draft_updates(
        self,
        org_id: str,
        draft: OrgPromptConfig,
        db: Session,
    ) -> tuple[dict[str, Any], list[OrgKnowledgeDoc]]:
        org = db.scalar(select(Organization).where(Organization.id == org_id))
        responses = db.scalars(
            select(OrgQuestionnaireResponse)
            .join(QuestionnaireQuestion, QuestionnaireQuestion.id == OrgQuestionnaireResponse.question_id)
            .where(OrgQuestionnaireResponse.org_id == org_id)
        ).all()
        questions = db.scalars(select(QuestionnaireQuestion).where(QuestionnaireQuestion.active.is_(True))).all()
        question_by_id = {question.id: question for question in questions}
        answers_by_key = {
            question_by_id[response.question_id].question_key: self._deserialize_answer(
                question_by_id[response.question_id],
                response.answer_value,
            )
            for response in responses
            if response.question_id in question_by_id
        }

        docs = db.scalars(
            select(OrgKnowledgeDoc)
            .join(OrgMaterial, OrgMaterial.id == OrgKnowledgeDoc.material_id)
            .where(
                OrgKnowledgeDoc.org_id == org_id,
                OrgKnowledgeDoc.extraction_type != "raw_chunk",
                OrgKnowledgeDoc.manager_approved.is_not(False),
                OrgMaterial.deleted_at.is_(None),
            )
            .order_by(OrgKnowledgeDoc.confidence.desc(), OrgKnowledgeDoc.created_at.asc())
        ).all()

        pricing_docs = [doc.content for doc in docs if doc.extraction_type == "pricing"]
        company_fact_docs = [doc.content for doc in docs if doc.extraction_type == "company_fact"]

        updates: dict[str, Any] = {
            "company_name": draft.company_name or (org.name if org is not None else ""),
            "product_category": answers_by_key.get("product_category") or draft.product_category or (org.industry if org is not None else ""),
            "product_description": answers_by_key.get("product_description")
            or draft.product_description
            or " ".join(self._dedupe_strings(company_fact_docs)[:2]),
            "pitch_stages": answers_by_key.get("pitch_stages") or list(draft.pitch_stages or []),
            "unique_selling_points": self._synthesize_field("unique_selling_points", docs, None) or list(draft.unique_selling_points or []),
            "known_objections": self._synthesize_field("known_objections", docs, answers_by_key.get("key_objections"))
            or list(draft.known_objections or []),
            "target_demographics": {
                "age_range": answers_by_key.get("target_age_range"),
                "homeowner_type": answers_by_key.get("target_homeowner_type"),
                "common_concerns": answers_by_key.get("common_homeowner_concerns") or [],
            },
            "competitors": self._synthesize_field("competitors", docs, answers_by_key.get("main_competitors"))
            or list(draft.competitors or []),
            "pricing_framing": answers_by_key.get("pricing_framing")
            or draft.pricing_framing
            or " ".join(self._dedupe_strings(pricing_docs)[:3]),
            "close_style": answers_by_key.get("close_style") or draft.close_style,
            "rep_tone_guidance": answers_by_key.get("rep_tone_guidance") or draft.rep_tone_guidance,
            "grading_priorities": answers_by_key.get("grading_priorities") or list(draft.grading_priorities or []),
        }
        updates["target_demographics"] = {
            key: value
            for key, value in updates["target_demographics"].items()
            if value not in (None, "", [])
        }
        return updates, docs

    def _deserialize_answer(self, question: QuestionnaireQuestion, answer_value: str) -> Any:
        if question.question_type == "multi_choice":
            try:
                parsed = json.loads(answer_value)
            except Exception:
                return [part.strip() for part in self._parse_lines(answer_value) if part.strip()]
            return parsed if isinstance(parsed, list) else [str(parsed)]
        return answer_value

    def _parse_lines(self, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raw = str(value).strip()
        if not raw:
            return []
        return [
            line.strip(" -*\t")
            for line in LINE_SPLIT_RE.split(raw)
            if line.strip(" -*\t")
        ]

    def _split_objection_hint(self, line: str) -> tuple[str | None, str | None]:
        for delimiter in ("->", "—", " - ", ":"):
            if delimiter in line:
                left, right = line.split(delimiter, 1)
                return left.strip() or None, right.strip() or None
        return line.strip() or None, None

    def _split_named_value(self, line: str) -> tuple[str | None, str | None]:
        for delimiter in ("->", "—", " - ", ":"):
            if delimiter in line:
                left, right = line.split(delimiter, 1)
                return left.strip() or None, right.strip() or None
        return line.strip() or None, None

    def _dedupe_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = " ".join(str(value).split()).strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            ordered.append(normalized)
        return ordered

    def _dedupe_object_rows(self, rows: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        ordered: list[dict[str, Any]] = []
        for row in rows:
            identifier = " ".join(str(row.get(key) or "").split()).strip().lower()
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            ordered.append(row)
        return ordered

    def _editable_config_fields(self) -> set[str]:
        blocked = {"id", "org_id", "created_at", "updated_at"}
        return {column.name for column in OrgPromptConfig.__table__.columns if column.name not in blocked}

    def _serialize_doc(self, doc: OrgKnowledgeDoc) -> dict[str, Any]:
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
