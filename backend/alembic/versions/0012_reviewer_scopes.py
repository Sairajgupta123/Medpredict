"""Add scoped reviewer grants and append-only scope audit events.

Revision ID: 0012_reviewer_scopes
Revises: 0011_catalog_audit_constraints
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_reviewer_scopes"
down_revision: Union[str, None] = "0011_catalog_audit_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create current scope grants and immutable grant/revocation events."""
    op.create_table(
        "catalog_reviewer_scopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=200), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=False),
        sa.Column("grant_reason", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_reviewer_scopes_type",
        ),
        sa.CheckConstraint(
            "scope_key IS NULL OR length(trim(scope_key)) >= 1",
            name="ck_catalog_reviewer_scopes_key",
        ),
        sa.CheckConstraint(
            "length(trim(grant_reason)) >= 8",
            name="ck_catalog_reviewer_scopes_grant_reason",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason IS NULL) "
            "OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL "
            "AND length(trim(revoke_reason)) >= 8)",
            name="ck_catalog_reviewer_scopes_revocation",
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reviewer_id", "scope_type", "scope_key",
            name="uq_catalog_reviewer_scope",
        ),
    )
    op.create_index(
        "ix_catalog_reviewer_scopes_reviewer_id",
        "catalog_reviewer_scopes",
        ["reviewer_id"],
    )
    op.create_index(
        "ix_catalog_reviewer_scopes_scope_type",
        "catalog_reviewer_scopes",
        ["scope_type"],
    )

    op.create_table(
        "catalog_reviewer_scope_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=200), nullable=True),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('granted', 'revoked')",
            name="ck_catalog_reviewer_scope_events_type",
        ),
        sa.CheckConstraint(
            "scope_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_reviewer_scope_events_scope_type",
        ),
        sa.CheckConstraint(
            "scope_key IS NULL OR length(trim(scope_key)) >= 1",
            name="ck_catalog_reviewer_scope_events_key",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_catalog_reviewer_scope_events_reason",
        ),
        sa.ForeignKeyConstraint(["scope_id"], ["catalog_reviewer_scopes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_reviewer_scope_events_scope_id",
        "catalog_reviewer_scope_events",
        ["scope_id"],
    )
    op.create_index(
        "ix_catalog_reviewer_scope_events_reviewer_id",
        "catalog_reviewer_scope_events",
        ["reviewer_id"],
    )
    op.create_index(
        "ix_catalog_reviewer_scope_events_created_at",
        "catalog_reviewer_scope_events",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop scope audit events before their referenced grants."""
    op.drop_index(
        "ix_catalog_reviewer_scope_events_created_at",
        table_name="catalog_reviewer_scope_events",
    )
    op.drop_index(
        "ix_catalog_reviewer_scope_events_reviewer_id",
        table_name="catalog_reviewer_scope_events",
    )
    op.drop_index(
        "ix_catalog_reviewer_scope_events_scope_id",
        table_name="catalog_reviewer_scope_events",
    )
    op.drop_table("catalog_reviewer_scope_events")
    op.drop_index(
        "ix_catalog_reviewer_scopes_scope_type",
        table_name="catalog_reviewer_scopes",
    )
    op.drop_index(
        "ix_catalog_reviewer_scopes_reviewer_id",
        table_name="catalog_reviewer_scopes",
    )
    op.drop_table("catalog_reviewer_scopes")
