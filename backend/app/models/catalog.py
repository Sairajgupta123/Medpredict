"""Curated disease and symptom catalog models."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Symptom(Base):
    """A normalized symptom term used by the text workflow."""

    __tablename__ = "symptoms"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DiseaseSymptom(Base):
    """Many-to-many catalog link between diseases and symptoms."""

    __tablename__ = "disease_symptoms"
    __table_args__ = (
        UniqueConstraint("disease_id", "symptom_id", name="uq_disease_symptom"),
    )

    disease_id: Mapped[UUID] = mapped_column(
        ForeignKey("diseases.id", ondelete="CASCADE"), primary_key=True
    )
    symptom_id: Mapped[UUID] = mapped_column(
        ForeignKey("symptoms.id", ondelete="CASCADE"), primary_key=True
    )
    relevance_weight: Mapped[float] = mapped_column(default=1.0)
