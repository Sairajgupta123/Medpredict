"""Index consumed verification tokens for bounded retention cleanup.

Revision ID: 0028_email_verification_used_at
Revises: 0027_deletion_claim_token
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028_email_verification_used_at"
down_revision: Union[str, None] = "0027_deletion_claim_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_email_verification_tokens_used_at",
        "email_verification_tokens",
        ["used_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_tokens_used_at",
        table_name="email_verification_tokens",
    )
