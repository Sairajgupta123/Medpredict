"""Allow dedicated skin-image scopes in reviewer governance.

Revision ID: 0020_skin_image_reviewer_scopes
Revises: 0019_skin_image_review
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0020_skin_image_reviewer_scopes"
down_revision: Union[str, None] = "0019_skin_image_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Extend both current-scope and immutable-event type constraints."""
    op.drop_constraint(
        "ck_catalog_reviewer_scopes_type",
        "catalog_reviewer_scopes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_reviewer_scopes_type",
        "catalog_reviewer_scopes",
        "scope_type IN ('disease', 'symptom', 'disease_symptom', 'skin_image')",
    )
    op.drop_constraint(
        "ck_catalog_reviewer_scope_events_scope_type",
        "catalog_reviewer_scope_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_reviewer_scope_events_scope_type",
        "catalog_reviewer_scope_events",
        "scope_type IN ('disease', 'symptom', 'disease_symptom', 'skin_image')",
    )


def downgrade() -> None:
    """Remove image-specific grants and restore catalog-only scope constraints."""
    # The downgraded schema cannot represent skin-image scopes. Remove their
    # dependent audit rows first, then their current grants.
    op.execute(
        "DELETE FROM catalog_reviewer_scope_events WHERE scope_type = 'skin_image'"
    )
    op.execute(
        "DELETE FROM catalog_reviewer_scopes WHERE scope_type = 'skin_image'"
    )
    op.drop_constraint(
        "ck_catalog_reviewer_scope_events_scope_type",
        "catalog_reviewer_scope_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_reviewer_scope_events_scope_type",
        "catalog_reviewer_scope_events",
        "scope_type IN ('disease', 'symptom', 'disease_symptom')",
    )
    op.drop_constraint(
        "ck_catalog_reviewer_scopes_type",
        "catalog_reviewer_scopes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_catalog_reviewer_scopes_type",
        "catalog_reviewer_scopes",
        "scope_type IN ('disease', 'symptom', 'disease_symptom')",
    )
