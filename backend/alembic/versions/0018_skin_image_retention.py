"""Add explicit skin-image retention schedule metadata.

Revision ID: 0018_skin_image_retention
Revises: 0017_skin_image_lifecycle
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_skin_image_retention"
down_revision: Union[str, None] = "0017_skin_image_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store an explicit expiry and policy version for retained image objects."""
    op.add_column(
        "skin_image_analyses",
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("retention_policy_version", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_skin_image_analyses_retention_expires_at",
        "skin_image_analyses",
        ["retention_expires_at"],
    )


def downgrade() -> None:
    """Remove image retention schedule metadata."""
    op.drop_index(
        "ix_skin_image_analyses_retention_expires_at",
        table_name="skin_image_analyses",
    )
    op.drop_column("skin_image_analyses", "retention_policy_version")
    op.drop_column("skin_image_analyses", "retention_expires_at")