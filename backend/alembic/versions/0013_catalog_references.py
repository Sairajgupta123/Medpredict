"""Add source-reference links and immutable catalog reference history.

Revision ID: 0013_catalog_references
Revises: 0012_reviewer_scopes
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_catalog_references"
down_revision: Union[str, None] = "0012_reviewer_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create catalog source links and append-only link events."""
    op.create_table(
        "catalog_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_key", sa.String(length=200), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by", sa.Uuid(), nullable=False),
        sa.Column("link_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("removed_by", sa.Uuid(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "target_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_references_target_type",
        ),
        sa.CheckConstraint(
            "length(trim(target_key)) >= 1",
            name="ck_catalog_references_target_key",
        ),
        sa.CheckConstraint(
            "length(trim(link_reason)) >= 8",
            name="ck_catalog_references_link_reason",
        ),
        sa.CheckConstraint(
            "(removed_at IS NULL AND removed_by IS NULL AND removal_reason IS NULL) "
            "OR (removed_at IS NOT NULL AND removed_by IS NOT NULL "
            "AND length(trim(removal_reason)) >= 8)",
            name="ck_catalog_references_removal",
        ),
        sa.ForeignKeyConstraint(["reference_id"], ["medical_references.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["linked_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["removed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_type", "target_key", "reference_id",
            name="uq_catalog_reference_target_source",
        ),
    )
    op.create_index("ix_catalog_references_target_type", "catalog_references", ["target_type"])
    op.create_index("ix_catalog_references_target_key", "catalog_references", ["target_key"])
    op.create_index("ix_catalog_references_reference_id", "catalog_references", ["reference_id"])

    op.create_table(
        "catalog_reference_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("catalog_reference_id", sa.Uuid(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_key", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('linked', 'removed')",
            name="ck_catalog_reference_events_type",
        ),
        sa.CheckConstraint(
            "target_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_reference_events_target_type",
        ),
        sa.CheckConstraint(
            "length(trim(target_key)) >= 1",
            name="ck_catalog_reference_events_target_key",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_catalog_reference_events_reason",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_reference_id"], ["catalog_references.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["reference_id"], ["medical_references.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_reference_events_catalog_reference_id",
        "catalog_reference_events", ["catalog_reference_id"],
    )
    op.create_index(
        "ix_catalog_reference_events_reference_id",
        "catalog_reference_events", ["reference_id"],
    )
    op.create_index(
        "ix_catalog_reference_events_target_type",
        "catalog_reference_events", ["target_type"],
    )
    op.create_index(
        "ix_catalog_reference_events_target_key",
        "catalog_reference_events", ["target_key"],
    )
    op.create_index(
        "ix_catalog_reference_events_actor_id",
        "catalog_reference_events", ["actor_id"],
    )
    op.create_index(
        "ix_catalog_reference_events_created_at",
        "catalog_reference_events", ["created_at"],
    )


def downgrade() -> None:
    """Drop link events before the current link table."""
    op.drop_table("catalog_reference_events")
    op.drop_table("catalog_references")
