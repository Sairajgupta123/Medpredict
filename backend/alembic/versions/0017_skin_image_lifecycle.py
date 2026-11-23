"""Add explicit skin-image consent purposes and deletion lifecycle state.

Revision ID: 0017_skin_image_lifecycle
Revises: 0016_user_token_version
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_skin_image_lifecycle"
down_revision: Union[str, None] = "0016_user_token_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Expand consent purposes and track image object deletion state."""
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
    op.add_column(
        "skin_image_analyses",
        sa.Column("storage_status", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE skin_image_analyses SET storage_status = 'unknown'")
    op.alter_column(
        "skin_image_analyses",
        "storage_status",
        existing_type=sa.String(length=24),
        nullable=False,
        server_default="pending_upload",
    )
    op.create_check_constraint(
        "ck_skin_image_storage_status",
        "skin_image_analyses",
        "storage_status IN ('unknown', 'pending_upload', 'stored', 'deletion_pending', 'deleted', 'failed')",
    )


def downgrade() -> None:
    """Restore the original consent purpose and image metadata schema."""
    op.drop_constraint(
        "ck_skin_image_storage_status", "skin_image_analyses", type_="check"
    )
    op.drop_column("skin_image_analyses", "deleted_at")
    op.drop_column("skin_image_analyses", "deletion_requested_at")
    op.drop_column("skin_image_analyses", "storage_status")
    op.drop_constraint(
        "ck_prediction_consent_purpose",
        "prediction_consent_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_prediction_consent_purpose",
        "prediction_consent_events",
        "purpose IN ('prediction_history')",
    )