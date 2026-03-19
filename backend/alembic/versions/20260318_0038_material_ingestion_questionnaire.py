"""add material ingestion and questionnaire tables

Revision ID: 20260318_0038
Revises: 20260318_0037
Create Date: 2026-03-18 17:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session
from sqlalchemy.types import UserDefinedType

from app.db.seed_questionnaire import seed_questionnaire_questions


class VectorType(UserDefinedType):
    def get_col_spec(self, **kw):
        return "VECTOR(1536)"


# revision identifiers, used by Alembic.
revision = "20260318_0038"
down_revision = "20260318_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    if "org_materials" not in inspector.get_table_names():
        op.create_table(
            "org_materials",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("original_filename", sa.String(length=255), nullable=False),
            sa.Column("file_type", sa.String(length=32), nullable=False),
            sa.Column("storage_key", sa.String(length=600), nullable=False),
            sa.Column("file_size_bytes", sa.Integer(), nullable=True),
            sa.Column("extraction_status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("extraction_error", sa.Text(), nullable=True),
            sa.Column("raw_transcript", sa.Text(), nullable=True),
            sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_org_materials_org_id", "org_materials", ["org_id"], unique=False)
        op.create_index("ix_org_materials_org_created", "org_materials", ["org_id", "created_at"], unique=False)
        op.create_index("ix_org_materials_org_status", "org_materials", ["org_id", "extraction_status"], unique=False)

    embedding_type = VectorType() if bind.dialect.name == "postgresql" else sa.JSON()
    inspector = sa.inspect(bind)
    if "org_knowledge_docs" not in inspector.get_table_names():
        op.create_table(
            "org_knowledge_docs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("material_id", sa.Integer(), sa.ForeignKey("org_materials.id", ondelete="CASCADE"), nullable=False),
            sa.Column("extraction_type", sa.String(length=64), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("supporting_quote", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("manager_approved", sa.Boolean(), nullable=True),
            sa.Column("used_in_config", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("embedding", embedding_type, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_org_knowledge_docs_org_id", "org_knowledge_docs", ["org_id"], unique=False)
        op.create_index(
            "ix_org_knowledge_docs_org_type_approved",
            "org_knowledge_docs",
            ["org_id", "extraction_type", "manager_approved"],
            unique=False,
        )
        op.create_index(
            "ix_org_knowledge_docs_material_type",
            "org_knowledge_docs",
            ["material_id", "extraction_type"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if "questionnaire_questions" not in inspector.get_table_names():
        op.create_table(
            "questionnaire_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("question_key", sa.String(length=120), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("question_type", sa.String(length=32), nullable=False),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("display_order", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(length=32), nullable=False),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("maps_to_config_field", sa.String(length=120), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("question_key", name="uq_questionnaire_questions_question_key"),
        )
        op.create_index(
            "ix_questionnaire_questions_active_category_order",
            "questionnaire_questions",
            ["active", "category", "display_order"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if "org_questionnaire_responses" not in inspector.get_table_names():
        op.create_table(
            "org_questionnaire_responses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("question_id", sa.Integer(), sa.ForeignKey("questionnaire_questions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("answer_value", sa.Text(), nullable=False),
            sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("org_id", "question_id", name="uq_org_questionnaire_response"),
        )
        op.create_index("ix_org_questionnaire_responses_org_id", "org_questionnaire_responses", ["org_id"], unique=False)
        op.create_index(
            "ix_org_questionnaire_responses_org_answered",
            "org_questionnaire_responses",
            ["org_id", "answered_at"],
            unique=False,
        )

    session = Session(bind=bind)
    try:
        seed_questionnaire_questions(session)
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    op.drop_index("ix_org_questionnaire_responses_org_answered", table_name="org_questionnaire_responses")
    op.drop_index("ix_org_questionnaire_responses_org_id", table_name="org_questionnaire_responses")
    op.drop_table("org_questionnaire_responses")

    op.drop_index("ix_questionnaire_questions_active_category_order", table_name="questionnaire_questions")
    op.drop_table("questionnaire_questions")

    op.drop_index("ix_org_knowledge_docs_material_type", table_name="org_knowledge_docs")
    op.drop_index("ix_org_knowledge_docs_org_type_approved", table_name="org_knowledge_docs")
    op.drop_index("ix_org_knowledge_docs_org_id", table_name="org_knowledge_docs")
    op.drop_table("org_knowledge_docs")

    op.drop_index("ix_org_materials_org_status", table_name="org_materials")
    op.drop_index("ix_org_materials_org_created", table_name="org_materials")
    op.drop_index("ix_org_materials_org_id", table_name="org_materials")
    op.drop_table("org_materials")
