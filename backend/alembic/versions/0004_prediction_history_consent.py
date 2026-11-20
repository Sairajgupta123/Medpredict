"""Add explicit prediction-history consent events and text-storage guard.

Revision ID: 0004_prediction_history_consent
Revises: 0003_reviewed_symptom_catalog
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_prediction_history_consent"
down_revision: Union[str, None] = "0003_reviewed_symptom_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record consent decisions and prevent unconsented symptom-text storage."""
    op.alter_column(
        "predictions",
        "input_storage_consent",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_prediction_text_requires_consent",
        "predictions",
        "input_text IS NULL OR input_storage_consent = true",
    )
    op.create_table(
        "prediction_consent_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.String(length=40),
            server_default="prediction_history",
            nullable=False,
        ),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.String(length=40), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('prediction_history')",
            name="ck_prediction_consent_purpose",
        ),
        sa.CheckConstraint(
            "action IN ('granted', 'revoked')",
            name="ck_prediction_consent_action",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"], ["predictions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prediction_consent_events_prediction_id",
        "prediction_consent_events",
        ["prediction_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove consent events and the health-text storage guard."""
    op.drop_index(
        "ix_prediction_consent_events_prediction_id",
        table_name="prediction_consent_events",
    )
    op.drop_table("prediction_consent_events")
    op.drop_constraint(
        "ck_prediction_text_requires_consent", "predictions", type_="check"
    )
    op.alter_column(
        "predictions",
        "input_storage_consent",
        existing_type=sa.Boolean(),
        server_default=None,
        existing_nullable=False,
    )
