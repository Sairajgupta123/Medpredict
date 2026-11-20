"""Curated disease and symptom catalog models."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Disease(Base):
    """A condition supported by the curated prediction catalog."""

    __tablename__ = "diseases"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_diseases_review_status",
        ),
        CheckConstraint(
            "review_status != 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_diseases_approval_audit",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    review_status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Symptom(Base):
    """A normalized symptom term with an explicit clinical review lifecycle."""

    __tablename__ = "symptoms"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_symptoms_review_status",
        ),
        CheckConstraint(
            "review_status != 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_symptoms_approval_audit",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    review_status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DiseaseSymptom(Base):
    """Clinically reviewed link between a disease and a symptom."""

    __tablename__ = "disease_symptoms"
    __table_args__ = (
        UniqueConstraint("disease_id", "symptom_id", name="uq_disease_symptom"),
        CheckConstraint(
            "review_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_disease_symptoms_review_status",
        ),
        CheckConstraint(
            "review_status != 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_disease_symptoms_approval_audit",
        ),
    )

    disease_id: Mapped[UUID] = mapped_column(
        ForeignKey("diseases.id", ondelete="CASCADE"), primary_key=True
    )
    symptom_id: Mapped[UUID] = mapped_column(
        ForeignKey("symptoms.id", ondelete="CASCADE"), primary_key=True
    )
    relevance_weight: Mapped[float] = mapped_column(default=1.0)
    review_status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

class CatalogReviewEvent(Base):
    """Append-only record of each reviewer decision on a catalog item."""

    __tablename__ = "catalog_review_events"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_review_events_target_type",
        ),
        CheckConstraint(
            "previous_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_catalog_review_events_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_catalog_review_events_new_status",
        ),
        CheckConstraint(
            "length(trim(target_key)) >= 1",
            name="ck_catalog_review_events_target_key",
        ),
        CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_catalog_review_events_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_key: Mapped[str] = mapped_column(String(200), index=True)
    previous_status: Mapped[str] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

