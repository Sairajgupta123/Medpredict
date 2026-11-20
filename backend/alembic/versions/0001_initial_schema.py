"""Create the initial MediPredict relational schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the initial tables and indexes."""
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "diseases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_diseases_code", "diseases", ["code"], unique=True)
    op.create_index("ix_diseases_name", "diseases", ["name"], unique=False)
    op.create_index("ix_diseases_is_active", "diseases", ["is_active"], unique=False)

    op.create_table(
        "symptoms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_symptoms_code", "symptoms", ["code"], unique=True)
    op.create_index("ix_symptoms_name", "symptoms", ["name"], unique=True)
    op.create_index("ix_symptoms_is_active", "symptoms", ["is_active"], unique=False)

    op.create_table(
        "disease_symptoms",
        sa.Column("disease_id", sa.Uuid(), nullable=False),
        sa.Column("symptom_id", sa.Uuid(), nullable=False),
        sa.Column("relevance_weight", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["disease_id"], ["diseases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symptom_id"], ["symptoms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("disease_id", "symptom_id"),
        sa.UniqueConstraint("disease_id", "symptom_id", name="uq_disease_symptom"),
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("modality", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("input_storage_consent", sa.Boolean(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("disclaimer_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("modality IN ('text', 'skin_image', 'combined')", name="ck_predictions_modality"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed', 'review_required')", name="ck_predictions_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_predictions_user_id", "predictions", ["user_id"], unique=False)
    op.create_index("ix_predictions_modality", "predictions", ["modality"], unique=False)
    op.create_index("ix_predictions_status", "predictions", ["status"], unique=False)
    op.create_index("ix_predictions_created_at", "predictions", ["created_at"], unique=False)

    op.create_table(
        "prediction_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("disease_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.CheckConstraint("rank >= 1", name="ck_prediction_result_rank_positive"),
        sa.CheckConstraint("probability >= 0 AND probability <= 1", name="ck_prediction_result_probability_range"),
        sa.ForeignKeyConstraint(["disease_id"], ["diseases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_id", "rank", name="uq_prediction_result_rank"),
    )
    op.create_index("ix_prediction_results_prediction_id", "prediction_results", ["prediction_id"], unique=False)
    op.create_index("ix_prediction_results_disease_id", "prediction_results", ["disease_id"], unique=False)

    op.create_table(
        "skin_image_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("predicted_class", sa.String(length=160), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=7, scale=6), nullable=True),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_id", name="uq_skin_image_prediction"),
    )
    op.create_index("ix_skin_image_analyses_prediction_id", "skin_image_analyses", ["prediction_id"], unique=False)
    op.create_index("ix_skin_image_analyses_image_sha256", "skin_image_analyses", ["image_sha256"], unique=False)

    op.create_table(
        "prediction_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("was_helpful", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prediction_feedback_prediction_id", "prediction_feedback", ["prediction_id"], unique=False)
    op.create_index("ix_prediction_feedback_review_status", "prediction_feedback", ["review_status"], unique=False)


def downgrade() -> None:
    """Drop tables in reverse dependency order."""
    op.drop_index("ix_prediction_feedback_review_status", table_name="prediction_feedback")
    op.drop_index("ix_prediction_feedback_prediction_id", table_name="prediction_feedback")
    op.drop_table("prediction_feedback")

    op.drop_index("ix_skin_image_analyses_image_sha256", table_name="skin_image_analyses")
    op.drop_index("ix_skin_image_analyses_prediction_id", table_name="skin_image_analyses")
    op.drop_table("skin_image_analyses")

    op.drop_index("ix_prediction_results_disease_id", table_name="prediction_results")
    op.drop_index("ix_prediction_results_prediction_id", table_name="prediction_results")
    op.drop_table("prediction_results")

    op.drop_index("ix_predictions_created_at", table_name="predictions")
    op.drop_index("ix_predictions_status", table_name="predictions")
    op.drop_index("ix_predictions_modality", table_name="predictions")
    op.drop_index("ix_predictions_user_id", table_name="predictions")
    op.drop_table("predictions")

    op.drop_table("disease_symptoms")

    op.drop_index("ix_symptoms_is_active", table_name="symptoms")
    op.drop_index("ix_symptoms_name", table_name="symptoms")
    op.drop_index("ix_symptoms_code", table_name="symptoms")
    op.drop_table("symptoms")

    op.drop_index("ix_diseases_is_active", table_name="diseases")
    op.drop_index("ix_diseases_name", table_name="diseases")
    op.drop_index("ix_diseases_code", table_name="diseases")
    op.drop_table("diseases")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
