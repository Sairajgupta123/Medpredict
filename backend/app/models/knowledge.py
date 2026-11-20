"""Reviewed medical references and care recommendations."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MedicalReference(Base):
    """A source record reviewed for use in the public medical knowledge base."""

    __tablename__ = "medical_references"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_medical_references_review_status",
        ),
        CheckConstraint(
            "review_status != 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_medical_reference_approval_audit",
        ),
        UniqueConstraint("url", "version", name="uq_medical_reference_url_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(300))
    publisher: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000))
    evidence_type: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(80), default="1")
    published_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    accessed_on: Mapped[date] = mapped_column(Date, default=date.today)
    license_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CareRecommendation(Base):
    """A human-reviewed general-care information item; never a prescription."""

    __tablename__ = "care_recommendations"
    __table_args__ = (
        CheckConstraint(
            "category IN ('general_care', 'precautions', 'lifestyle', 'diet', "
            "'when_to_seek_care', 'emergency_signs')",
            name="ck_care_recommendations_category",
        ),
        CheckConstraint(
            "urgency IN ('routine', 'prompt', 'urgent', 'emergency')",
            name="ck_care_recommendations_urgency",
        ),
        CheckConstraint(
            "review_status IN ('draft', 'in_review', 'approved', 'retired')",
            name="ck_care_recommendations_review_status",
        ),
        CheckConstraint(
            "review_status != 'approved' OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_care_recommendation_approval_audit",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="ck_care_recommendation_validity_window",
        ),
        UniqueConstraint("code", "version", name="uq_care_recommendation_code_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    disease_id: Mapped[UUID] = mapped_column(
        ForeignKey("diseases.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column(String(80), default="1")
    locale: Mapped[str] = mapped_column(String(12), default="en")
    category: Mapped[str] = mapped_column(String(32), index=True)
    urgency: Mapped[str] = mapped_column(String(16), default="routine", index=True)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_review_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    references: Mapped[list["RecommendationReference"]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )


class RecommendationReference(Base):
    """Provenance link from a recommendation version to a source version."""

    __tablename__ = "recommendation_references"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id", "reference_id",
            name="uq_recommendation_reference",
        ),
    )

    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("care_recommendations.id", ondelete="CASCADE"), primary_key=True
    )
    reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("medical_references.id", ondelete="RESTRICT"), primary_key=True
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    recommendation: Mapped[CareRecommendation] = relationship(back_populates="references")
    reference: Mapped[MedicalReference] = relationship()
