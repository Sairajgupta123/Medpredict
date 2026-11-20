"""Scoped reviewer assignments and immutable assignment audit events."""

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


class CatalogReviewerScope(Base):
    """Current access grant for one reviewer and one catalog scope."""

    __tablename__ = "catalog_reviewer_scopes"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_reviewer_scopes_type",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason IS NULL) "
            "OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL "
            "AND length(trim(revoke_reason)) >= 8)",
            name="ck_catalog_reviewer_scopes_revocation",
        ),
        UniqueConstraint(
            "reviewer_id", "scope_type", "scope_key",
            name="uq_catalog_reviewer_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    scope_type: Mapped[str] = mapped_column(String(32), index=True)
    # NULL means all entries of this type; otherwise an exact catalog key.
    scope_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    granted_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    grant_reason: Mapped[str] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CatalogReviewerScopeEvent(Base):
    """Immutable record of each reviewer scope grant or revocation."""

    __tablename__ = "catalog_reviewer_scope_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('granted', 'revoked')",
            name="ck_catalog_reviewer_scope_events_type",
        ),
        CheckConstraint(
            "scope_type IN ('disease', 'symptom', 'disease_symptom')",
            name="ck_catalog_reviewer_scope_events_scope_type",
        ),
        CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_catalog_reviewer_scope_events_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog_reviewer_scopes.id", ondelete="RESTRICT"), index=True
    )
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(20))
    scope_type: Mapped[str] = mapped_column(String(32))
    scope_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
