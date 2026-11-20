"""Create hashed, expiring password reset tokens.

Revision ID: 0014_password_reset_tokens
Revises: 0013_catalog_references
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_password_reset_tokens"
down_revision: Union[str, None] = "0013_catalog_references"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create storage for hashed single-use password reset tokens."""
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
    )
    op.create_index(
        "ix_password_reset_tokens_expires_at",
        "password_reset_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    """Remove password reset token storage."""
    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
