"""Require audited approval before disease catalog publication.

Revision ID: 0006_disease_catalog_review
Revises: 0005_merge_knowledge_consent
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_disease_catalog_review"
down_revision: Union[str, None] = "0005_merge_knowledge_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Existing disease rows start as drafts until reviewed explicitly."""
    op.add_column(
        "diseases",
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default="draft",
            nullable=False,
        ),
    )
    op.add_column(
        "diseases",
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "diseases",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_diseases_review_status",
        "diseases",
        "review_status IN ('draft', 'in_review', 'approved', 'retired')",
    )
    op.create_check_constraint(
        "ck_diseases_approval_audit",
        "diseases",
        "review_status != 'approved' OR "
        "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
    )
    op.create_index(
        "ix_diseases_review_status", "diseases", ["review_status"], unique=False
    )


def downgrade() -> None:
    """Remove disease review governance fields and constraints."""
    op.drop_index("ix_diseases_review_status", table_name="diseases")
    op.drop_constraint("ck_diseases_approval_audit", "diseases", type_="check")
    op.drop_constraint("ck_diseases_review_status", "diseases", type_="check")
    op.drop_column("diseases", "reviewed_at")
    op.drop_column("diseases", "reviewed_by")
    op.drop_column("diseases", "review_status")
