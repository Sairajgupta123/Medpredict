"""Audit reviewer assignment removal during account deactivation.

Revision ID: 0023_skin_image_unassignment_audit
Revises: 0022_skin_image_review_consent
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0023_skin_image_unassignment_audit"
down_revision: Union[str, None] = "0022_skin_image_review_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow an immutable audit event for clearing a review assignment."""
    op.drop_constraint(
        "ck_skin_image_review_event_type",
        "skin_image_review_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_skin_image_review_event_type",
        "skin_image_review_events",
        "event_type IN ('assigned', 'reassigned', 'unassigned', 'image_accessed', 'reviewed')",
    )


def downgrade() -> None:
    """Remove unassignment events before restoring the prior event constraint."""
    op.execute(
        "DELETE FROM skin_image_review_events WHERE event_type = 'unassigned'"
    )
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
