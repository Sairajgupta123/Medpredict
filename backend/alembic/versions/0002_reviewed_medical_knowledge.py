"""Add reviewed medical references and care recommendations.

Revision ID: 0002_reviewed_medical_knowledge
Revises: 0001_initial_schema
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_reviewed_medical_knowledge"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create provenance-aware medical knowledge tables."""
    op.create_table(
        "medical_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("publisher", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("accessed_on", sa.Date(), nullable=False),
        sa.Column("license_name", sa.String(length=200), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "review_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_medical_references_review_status",
        ),
        sa.CheckConstraint(
            "review_status != 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_medical_reference_approval_audit",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", "version", name="uq_medical_reference_url_version"),
    )
    op.create_index(
        "ix_medical_references_review_status",
        "medical_references", ["review_status"], unique=False,
    )

    op.create_table(
        "care_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("disease_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("locale", sa.String(length=12), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("urgency", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('general_care', 'precautions', 'lifestyle', 'diet', "
            "'when_to_seek_care', 'emergency_signs')",
            name="ck_care_recommendations_category",
        ),
        sa.CheckConstraint(
            "urgency IN ('routine', 'prompt', 'urgent', 'emergency')",
            name="ck_care_recommendations_urgency",
        ),
        sa.CheckConstraint(
            "review_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_care_recommendations_review_status",
        ),
        sa.CheckConstraint(
            "review_status != 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_care_recommendation_approval_audit",
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="ck_care_recommendation_validity_window",
        ),
        sa.ForeignKeyConstraint(
            ["disease_id"], ["diseases.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "code", "version", name="uq_care_recommendation_code_version"
        ),
    )
    for column in ("disease_id", "code", "category", "urgency", "review_status", "is_active"):
        op.create_index(
            f"ix_care_recommendations_{column}",
            "care_recommendations", [column], unique=False,
        )

    op.create_table(
        "recommendation_references",
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["care_recommendations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"], ["medical_references.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("recommendation_id", "reference_id"),
        sa.UniqueConstraint(
            "recommendation_id", "reference_id",
            name="uq_recommendation_reference",
        ),
    )


def downgrade() -> None:
    """Drop knowledge tables in reverse dependency order."""
    op.drop_table("recommendation_references")
    for column in ("is_active", "review_status", "urgency", "category", "code", "disease_id"):
        op.drop_index(
            f"ix_care_recommendations_{column}",
            table_name="care_recommendations",
        )
    op.drop_table("care_recommendations")
    op.drop_index(
        "ix_medical_references_review_status",
        table_name="medical_references",
    )
    op.drop_table("medical_references")
