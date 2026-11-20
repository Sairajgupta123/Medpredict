"""Prediction records for text and skin-image workflows."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Prediction(Base):
    """A prediction request and its processing lifecycle.

    Raw symptom text is optional and should only be persisted when the user
    has explicitly consented to history storage. The service layer must enforce
    that rule and the configured retention policy.
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
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    modality: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_storage_consent: Mapped[bool] = mapped_column(default=False)
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
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    prediction_id: Mapped[UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(100))
    image_sha256: Mapped[str] = mapped_column(String(64), index=True)
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
