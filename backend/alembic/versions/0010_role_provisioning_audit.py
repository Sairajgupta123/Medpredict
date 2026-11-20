"""Add append-only reviewer role provisioning audit records.

Revision ID: 0010_role_provisioning_audit
Revises: 0009_catalog_review_audit
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_role_provisioning_audit"
down_revision: Union[str, None] = "0009_catalog_review_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record the operator and reason for every reviewer-role change."""
    op.create_table(
        "role_provisioning_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=False),
        sa.Column("previous_role", sa.String(length=20), nullable=False),
        sa.Column("new_role", sa.String(length=20), nullable=False),
        sa.Column("operator_identity", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "previous_role IN ('patient', 'reviewer', 'admin')",
            name="ck_role_provisioning_previous_role",
        ),
        sa.CheckConstraint(
            "new_role IN ('patient', 'reviewer')",
            name="ck_role_provisioning_new_role",
        ),
        sa.CheckConstraint(
            "length(trim(operator_identity)) >= 3",
            name="ck_role_provisioning_operator_identity",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_role_provisioning_reason",
        ),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_role_provisioning_events_target_user_id",
        "role_provisioning_events",
        ["target_user_id"],
    )
    op.create_index(
        "ix_role_provisioning_events_created_at",
        "role_provisioning_events",
        ["created_at"],
    )


def downgrade() -> None:
    """Remove role provisioning audit records."""
    op.drop_index(
        "ix_role_provisioning_events_created_at",
        table_name="role_provisioning_events",
    )
    op.drop_index(
        "ix_role_provisioning_events_target_user_id",
        table_name="role_provisioning_events",
    )
    op.drop_table("role_provisioning_events")
