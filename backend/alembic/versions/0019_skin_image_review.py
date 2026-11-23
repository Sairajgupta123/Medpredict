"""Add assigned human skin-image review workflow.

Revision ID: 0019_skin_image_review
Revises: 0018_skin_image_retention
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_skin_image_review"
down_revision: Union[str, None] = "0018_skin_image_retention"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skin_image_analyses",
        sa.Column("review_status", sa.String(length=24), server_default="pending", nullable=False),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("assigned_reviewer_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("assigned_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("review_outcome", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "skin_image_analyses",
        sa.Column("reviewer_note", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_skin_image_assigned_reviewer", "skin_image_analyses", "users",
        ["assigned_reviewer_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_skin_image_assigned_by", "skin_image_analyses", "users",
        ["assigned_by"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_skin_image_analyses_assigned_reviewer_id",
        "skin_image_analyses", ["assigned_reviewer_id"],
    )
    op.create_check_constraint(
        "ck_skin_image_review_status", "skin_image_analyses",
        "review_status IN ('pending', 'assigned', 'reviewed', 'unable_to_assess')",
    )
    op.create_check_constraint(
        "ck_skin_image_review_outcome", "skin_image_analyses",
        "review_outcome IS NULL OR review_outcome IN ('image_adequate', 'unable_to_assess')",
    )

    op.create_table(
        "skin_image_review_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("prediction_id", sa.Uuid(), sa.ForeignKey("predictions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("image_analysis_id", sa.Uuid(), sa.ForeignKey("skin_image_analyses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_reviewer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('assigned', 'reassigned', 'reviewed')",
            name="ck_skin_image_review_event_type",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_skin_image_review_event_reason",
        ),
    )
    op.create_index("ix_skin_image_review_events_prediction_id", "skin_image_review_events", ["prediction_id"])
    op.create_index("ix_skin_image_review_events_image_analysis_id", "skin_image_review_events", ["image_analysis_id"])
    op.create_index("ix_skin_image_review_events_actor_id", "skin_image_review_events", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_skin_image_review_events_actor_id", table_name="skin_image_review_events")
    op.drop_index("ix_skin_image_review_events_image_analysis_id", table_name="skin_image_review_events")
    op.drop_index("ix_skin_image_review_events_prediction_id", table_name="skin_image_review_events")
    op.drop_table("skin_image_review_events")
    op.drop_constraint("ck_skin_image_review_outcome", "skin_image_analyses", type_="check")
    op.drop_constraint("ck_skin_image_review_status", "skin_image_analyses", type_="check")
    op.drop_index("ix_skin_image_analyses_assigned_reviewer_id", table_name="skin_image_analyses")
    op.drop_constraint("fk_skin_image_assigned_by", "skin_image_analyses", type_="foreignkey")
    op.drop_constraint("fk_skin_image_assigned_reviewer", "skin_image_analyses", type_="foreignkey")
    op.drop_column("skin_image_analyses", "reviewer_note")
    op.drop_column("skin_image_analyses", "review_outcome")
    op.drop_column("skin_image_analyses", "reviewed_at")
    op.drop_column("skin_image_analyses", "assigned_at")
    op.drop_column("skin_image_analyses", "assigned_by")
    op.drop_column("skin_image_analyses", "assigned_reviewer_id")
    op.drop_column("skin_image_analyses", "review_status")
