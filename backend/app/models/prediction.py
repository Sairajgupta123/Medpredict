"""Prediction records, privacy consent events, and image-analysis metadata."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Prediction(Base):
    """A prediction request and its processing lifecycle.

    Raw symptom text must remain null unless explicit history-storage consent
    has been captured. The service layer must additionally verify a matching
    consent event and enforce retention/deletion policy.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint(
            "modality IN ('text', 'skin_image', 'combined')",
            name="ck_predictions_modality",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'review_required')",
            name="ck_predictions_status",
        ),
        CheckConstraint(
            "input_text IS NULL OR input_storage_consent = true",
            name="ck_prediction_text_requires_consent",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    modality: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_storage_consent: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), nullable=False
    )
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    disclaimer_version: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PredictionConsentEvent(Base):
    """Append-only record of a user's history-storage consent decision."""

    __tablename__ = "prediction_consent_events"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('prediction_history', 'skin_image_processing', 'skin_image_history')",
            name="ck_prediction_consent_purpose",
        ),
        CheckConstraint(
            "action IN ('granted', 'revoked')",
            name="ck_prediction_consent_action",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    prediction_id: Mapped[UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(
        String(40), default="prediction_history", server_default="prediction_history"
    )
    action: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[str] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PredictionResult(Base):
    """One ranked candidate condition returned by a prediction."""

    __tablename__ = "prediction_results"
    __table_args__ = (
        UniqueConstraint("prediction_id", "rank", name="uq_prediction_result_rank"),
        CheckConstraint("rank >= 1", name="ck_prediction_result_rank_positive"),
        CheckConstraint(
            "probability >= 0 AND probability <= 1",
            name="ck_prediction_result_probability_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    prediction_id: Mapped[UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), index=True
    )
    disease_id: Mapped[UUID] = mapped_column(
        ForeignKey("diseases.id", ondelete="RESTRICT"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer)
    probability: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)


class SkinImageAnalysis(Base):
    """Metadata for a skin-image analysis; image bytes live in object storage."""

    __tablename__ = "skin_image_analyses"
    __table_args__ = (
        UniqueConstraint("prediction_id", name="uq_skin_image_prediction"),
        CheckConstraint(
            "storage_status IN ('unknown', 'pending_upload', 'stored', 'deletion_pending', 'deleted', 'failed')",
            name="ck_skin_image_storage_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    prediction_id: Mapped[UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(100))
    image_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_status: Mapped[str] = mapped_column(
        String(24), default="pending_upload", server_default="pending_upload"
    )
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    retention_policy_version: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    predicted_class: Mapped[str | None] = mapped_column(String(160), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 6), nullable=True
    )
    quality_status: Mapped[str] = mapped_column(
        String(32), default="not_checked"
    )
    review_required: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
