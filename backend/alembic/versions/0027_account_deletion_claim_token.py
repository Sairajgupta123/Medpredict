"""Add fencing tokens to account deletion worker claims.

Revision ID: 0027_account_deletion_claim_token
Revises: 0026_skin_unassign
Create Date: 2026-11-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0027_account_deletion_claim_token"
down_revision: Union[str, None] = "0026_skin_unassign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "account_deletion_requests",
        sa.Column("claim_token", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("account_deletion_requests", "claim_token")
