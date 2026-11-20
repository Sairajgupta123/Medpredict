"""Strengthen catalog review audit event constraints.

Revision ID: 0011_catalog_audit_constraints
Revises: 0010_role_provisioning_audit
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011_catalog_audit_constraints"
down_revision: Union[str, None] = "0010_role_provisioning_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Constrain both sides of each status transition and its target key."""
    op.create_check_constraint(
        "ck_catalog_review_events_previous_status",
        "catalog_review_events",
        "previous_status IN ('draft', 'in_review', 'approved', 'retired')",
    )
    op.create_check_constraint(
        "ck_catalog_review_events_target_key",
        "catalog_review_events",
        "length(trim(target_key)) >= 1",
    )


def downgrade() -> None:
    """Remove the additional audit event constraints."""
    op.drop_constraint(
        "ck_catalog_review_events_target_key",
        "catalog_review_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_catalog_review_events_previous_status",
        "catalog_review_events",
        type_="check",
    )
