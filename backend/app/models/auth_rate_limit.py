"""Persistent request-throttling buckets for authentication endpoints."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthRateLimitBucket(Base):
    """Store counters without retaining raw email identifiers."""

    __tablename__ = "auth_rate_limit_buckets"
    __table_args__ = (
        Index("ix_auth_rate_limit_buckets_window_started_at", "window_started_at"),
    )

    bucket_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
