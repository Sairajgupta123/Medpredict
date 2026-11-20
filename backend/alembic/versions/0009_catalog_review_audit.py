"""Create append-only catalog review audit events.

Revision ID: 0009_catalog_review_audit
Revises: 0008_catalog_reviewer_roles
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_catalog_review_audit"
down_revision: Union[str, None] = "0008_catalog_reviewer_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store every catalog review decision with actor, reason, and timestamp."""
    op.create_table(
        "catalog_review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_key", sa.String(length=200), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=False),
        sa.Column("new_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_review_events_target_type",
        ),
        sa.CheckConstraint(
            "new_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_catalog_review_events_new_status",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_catalog_review_events_reason",
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_review_events_target_type",
        "catalog_review_events",
        ["target_type"],
    )
    op.create_index(
        "ix_catalog_review_events_target_key",
        "catalog_review_events",
        ["target_key"],
    )
    op.create_index(
        "ix_catalog_review_events_new_status",
        "catalog_review_events",
        ["new_status"],
    )
    op.create_index(
        "ix_catalog_review_events_reviewer_id",
        "catalog_review_events",
        ["reviewer_id"],
    )
    op.create_index(
        "ix_catalog_review_events_created_at",
        "catalog_review_events",
        ["created_at"],
    )


def downgrade() -> None:
    """Remove the review audit event table."""
    op.drop_index("ix_catalog_review_events_created_at", table_name="catalog_review_events")
    op.drop_index("ix_catalog_review_events_reviewer_id", table_name="catalog_review_events")
    op.drop_index("ix_catalog_review_events_new_status", table_name="catalog_review_events")
    op.drop_index("ix_catalog_review_events_target_key", table_name="catalog_review_events")
    op.drop_index("ix_catalog_review_events_target_type", table_name="catalog_review_events")
    op.drop_table("catalog_review_events")
