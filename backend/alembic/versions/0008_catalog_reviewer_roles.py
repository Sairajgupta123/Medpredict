"""Add role-based catalog review authorization.

Revision ID: 0008_catalog_reviewer_roles
Revises: 0007_disease_symptom_link_review
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_catalog_reviewer_roles"
down_revision: Union[str, None] = "0007_disease_symptom_link_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """All existing and newly registered users remain ordinary patients."""
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), server_default="patient", nullable=False),
    )
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('patient', 'reviewer', 'admin')",
    )


def downgrade() -> None:
    """Remove role-based authorization."""
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
