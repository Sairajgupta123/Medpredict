"""Add review lifecycle and approval audit fields to symptoms.

Revision ID: 0003_reviewed_symptom_catalog
Revises: 0002_reviewed_medical_knowledge
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_reviewed_symptom_catalog"
down_revision: Union[str, None] = "0002_reviewed_medical_knowledge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Default existing symptoms to draft; require audited approval to publish."""
    op.add_column(
        "symptoms",
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default="draft",
            nullable=False,
        ),
    )
    op.add_column(
        "symptoms",
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "symptoms",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_symptoms_review_status",
        "symptoms",
        "review_status IN ('draft', 'in_review', 'approved', 'retired')",
    )
    op.create_check_constraint(
        "ck_symptoms_approval_audit",
        "symptoms",
        "review_status != 'approved' OR "
        "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
    )
    op.create_index(
        "ix_symptoms_review_status", "symptoms", ["review_status"], unique=False
    )


def downgrade() -> None:
    """Remove symptom review governance fields."""
    op.drop_index("ix_symptoms_review_status", table_name="symptoms")
    op.drop_constraint("ck_symptoms_approval_audit", "symptoms", type_="check")
    op.drop_constraint("ck_symptoms_review_status", "symptoms", type_="check")
    op.drop_column("symptoms", "reviewed_at")
    op.drop_column("symptoms", "reviewed_by")
    op.drop_column("symptoms", "review_status")
