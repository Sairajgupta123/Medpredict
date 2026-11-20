"""User account model."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """A registered MediPredict account.

    Predictions may also be created without an account, so the prediction's
    user foreign key is nullable. Passwords must only ever be stored as hashes.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('patient', 'reviewer', 'admin')",
            name="ck_users_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    role: Mapped[str] = mapped_column(
        String(20), default="patient", server_default="patient", nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

class RoleProvisioningEvent(Base):
    """Append-only operational record of controlled reviewer-role changes."""

    __tablename__ = "role_provisioning_events"
    __table_args__ = (
        CheckConstraint(
            "previous_role IN ('patient', 'reviewer', 'admin')",
            name="ck_role_provisioning_previous_role",
        ),
        CheckConstraint(
            "new_role IN ('patient', 'reviewer')",
            name="ck_role_provisioning_new_role",
        ),
        CheckConstraint(
            "length(trim(operator_identity)) >= 3",
            name="ck_role_provisioning_operator_identity",
        ),
        CheckConstraint(
            "length(trim(reason)) >= 8",
            name="ck_role_provisioning_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    previous_role: Mapped[str] = mapped_column(String(20))
    new_role: Mapped[str] = mapped_column(String(20))
    operator_identity: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

