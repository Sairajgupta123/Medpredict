"""Source-reference links and audit events for catalog entries."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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


class CatalogReference(Base):
    """Current source link for a disease, symptom, or disease-symptom relation."""

    __tablename__ = "catalog_references"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_references_target_type",
        ),
        CheckConstraint(
            "length(trim(target_key)) >= 1",
            name="ck_catalog_references_target_key",
        ),
        CheckConstraint(
            "length(trim(link_reason)) >= 8",
            name="ck_catalog_references_link_reason",
        ),
        CheckConstraint(
            "(removed_at IS NULL AND removed_by IS NULL AND removal_reason IS NULL) "
            "OR (removed_at IS NOT NULL AND removed_by IS NOT NULL "
            "AND length(trim(removal_reason)) >= 8)",
            name="ck_catalog_references_removal",
        ),
        UniqueConstraint(
            "target_type", "target_key", "reference_id",
            name="uq_catalog_reference_target_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_key: Mapped[str] = mapped_column(String(200), index=True)
    reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("medical_references.id", ondelete="RESTRICT"), index=True
    )
    linked_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    link_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    removed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    removal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CatalogReferenceEvent(Base):
    """Append-only history of source links added to or removed from catalog entries."""

    __tablename__ = "catalog_reference_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('linked', 'removed')",
            name="ck_catalog_reference_events_type",
        ),
        CheckConstraint(
            "target_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_reference_events_target_type",
        ),
        CheckConstraint(
            "length(trim(target_key)) >= 1",
            name="ck_catalog_reference_events_target_key",
        ),
        CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_catalog_reference_events_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    catalog_reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog_references.id", ondelete="RESTRICT"), index=True
    )
    reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("medical_references.id", ondelete="RESTRICT"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_key: Mapped[str] = mapped_column(String(200), index=True)
    event_type: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
