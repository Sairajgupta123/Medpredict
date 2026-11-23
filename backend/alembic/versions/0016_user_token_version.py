"""Add per-user access-token versioning for session revocation.

Revision ID: 0016_user_token_version
Revises: 0015_merge_ref_reset_heads
Create Date: 2026-11-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_user_token_version"
down_revision: Union[str, None] = "0015_merge_ref_reset_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a version counter used to revoke previously issued access tokens."""
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Remove access-token versioning from user accounts."""
    op.drop_column("users", "token_version")
