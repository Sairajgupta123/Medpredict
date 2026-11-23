"""Audit successful private skin-image retrievals.

Revision ID: 0021_skin_image_access_audit
Revises: 0020_skin_image_reviewer_scopes
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0021_skin_image_access_audit"
down_revision: Union[str, None] = "0020_skin_image_reviewer_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow successful image retrievals in the append-only review event log."""
    op.drop_constraint(
        "ck_skin_image_review_event_type",
        "skin_image_review_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_skin_image_review_event_type",
        "skin_image_review_events",
        "event_type IN ('assigned', 'reassigned', 'image_accessed', 'reviewed')",
    )


def downgrade() -> None:
    """Remove image-access events before restoring the prior event vocabulary."""
    op.execute(
        "DELETE FROM skin_image_review_events WHERE event_type = 'image_accessed'"
    )
    op.drop_constraint(
        "ck_skin_image_review_event_type",
        "skin_image_review_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_skin_image_review_event_type",
        "skin_image_review_events",
        "event_type IN ('assigned', 'reassigned', 'reviewed')",
    )
