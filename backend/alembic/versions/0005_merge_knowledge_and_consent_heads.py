"""Merge reviewed-knowledge and prediction-consent migration branches.

Revision ID: 0005_merge_knowledge_and_consent_heads
Revises: 0004_knowledge_review_due_dates, 0004_prediction_history_consent
Create Date: 2026-11-20
"""

from typing import Sequence, Union

revision: str = "0005_merge_knowledge_and_consent_heads"
down_revision: Union[str, tuple[str, str], None] = (
    "0004_knowledge_review_due_dates",
    "0004_prediction_history_consent",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join two independent schema changes; both parent migrations are applied."""
    pass


def downgrade() -> None:
    """A merge revision has no schema operations to reverse."""
    pass
