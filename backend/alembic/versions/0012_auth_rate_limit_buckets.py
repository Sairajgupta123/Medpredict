"""Add persistent authentication rate-limit buckets.

Revision ID: 0012_auth_rate_limit_buckets
Revises: 0011_catalog_audit_constraints
Create Date: 2026-11-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_auth_rate_limit_buckets"
down_revision: Union[str, None] = "0011_catalog_audit_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create shared counters for auth endpoint throttling."""
    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("bucket_key", sa.String(length=64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    """Remove authentication throttle state."""
    op.drop_table("auth_rate_limit_buckets")
