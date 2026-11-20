"""Add scheduled review due dates to medical sources and recommendations.

Revision ID: 0004_knowledge_review_due_dates
Revises: 0003_reviewed_symptom_catalog
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_knowledge_review_due_dates"
down_revision: Union[str, None] = "0003_reviewed_symptom_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add optional dates after which approved content must be reviewed again."""
    op.add_column(
        "medical_references",
        sa.Column("next_review_due", sa.Date(), nullable=True),
    )
    op.add_column(
        "care_recommendations",
        sa.Column("next_review_due", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    """Remove scheduled review due dates."""
    op.drop_column("care_recommendations", "next_review_due")
    op.drop_column("medical_references", "next_review_due")
