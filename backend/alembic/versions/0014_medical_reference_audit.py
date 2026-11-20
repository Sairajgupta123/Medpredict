"""Add immutable medical reference lifecycle audit events.

Revision ID: 0014_medical_reference_audit
Revises: 0013_catalog_references
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_medical_reference_audit"
down_revision: Union[str, None] = "0013_catalog_references"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create append-only medical source registration/review history."""
    op.create_table(
        "medical_reference_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created', 'status_changed')",
            name="ck_medical_reference_events_type",
        ),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('draft', 'in_review', 'approved', 'retired')",
            name="ck_medical_reference_events_previous_status",
        ),
        sa.CheckConstraint(
            "new_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_medical_reference_events_new_status",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_medical_reference_events_reason",
        ),
        sa.ForeignKeyConstraint(["reference_id"], ["medical_references.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_medical_reference_events_reference_id",
        "medical_reference_events", ["reference_id"],
    )
    op.create_index(
        "ix_medical_reference_events_actor_id",
        "medical_reference_events", ["actor_id"],
    )
    op.create_index(
        "ix_medical_reference_events_created_at",
        "medical_reference_events", ["created_at"],
    )


def downgrade() -> None:
    """Drop the reference lifecycle audit table."""
    op.drop_table("medical_reference_events")
