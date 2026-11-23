"""Add a separate consent purpose for human skin-image review.

Revision ID: 0022_skin_image_review_consent
Revises: 0021_skin_image_access_audit
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0022_skin_image_review_consent"
down_revision: Union[str, None] = "0021_skin_image_access_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow an independently recorded human-review consent decision."""
    op.drop_constraint(
        "ck_prediction_consent_purpose",
        "prediction_consent_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_prediction_consent_purpose",
        "prediction_consent_events",
        "purpose IN ('prediction_history', 'skin_image_processing', 'skin_image_history', 'skin_image_review')",
    )


def downgrade() -> None:
    """Remove review-purpose consent events before restoring the old constraint."""
    op.execute(
        "DELETE FROM prediction_consent_events WHERE purpose = 'skin_image_review'"
    )
    op.drop_constraint(
        "ck_prediction_consent_purpose",
        "prediction_consent_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_prediction_consent_purpose",
        "prediction_consent_events",
        "purpose IN ('prediction_history', 'skin_image_processing', 'skin_image_history')",
    )
