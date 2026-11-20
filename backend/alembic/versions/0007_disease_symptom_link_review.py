"""Require audited approval for disease-symptom catalog links.

Revision ID: 0007_disease_symptom_link_review
Revises: 0006_disease_catalog_review
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_disease_symptom_link_review"
down_revision: Union[str, None] = "0006_disease_catalog_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Keep existing links unpublished until each association is reviewed."""
    op.add_column(
        "disease_symptoms",
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default="draft",
            nullable=False,
        ),
    )
    op.add_column(
        "disease_symptoms",
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "disease_symptoms",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_disease_symptoms_review_status",
        "disease_symptoms",
        "review_status IN ('draft', 'in_review', 'approved', 'retired')",
    )
    op.create_check_constraint(
        "ck_disease_symptoms_approval_audit",
        "disease_symptoms",
        "review_status != 'approved' OR "
        "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
    )
    op.create_index(
        "ix_disease_symptoms_review_status",
        "disease_symptoms",
        ["review_status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove disease-symptom association review governance."""
    op.drop_index(
        "ix_disease_symptoms_review_status", table_name="disease_symptoms"
    )
    op.drop_constraint(
        "ck_disease_symptoms_approval_audit", "disease_symptoms", type_="check"
    )
    op.drop_constraint(
        "ck_disease_symptoms_review_status", "disease_symptoms", type_="check"
    )
    op.drop_column("disease_symptoms", "reviewed_at")
    op.drop_column("disease_symptoms", "reviewed_by")
    op.drop_column("disease_symptoms", "review_status")
