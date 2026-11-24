"""Database-backed throttling for authentication requests."""

from datetime import datetime, timedelta, timezone
from math import ceil
import hashlib
import hmac

from fastapi import HTTPException, status
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.auth_rate_limit import AuthRateLimitBucket


def enforce_auth_rate_limit(
    db: Session,
    scope: str,
    identity: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    """Atomically count an authentication attempt and reject over-limit calls.

    HMAC-derived keys prevent raw email addresses from being stored in the
    throttle table. PostgreSQL and SQLite use atomic upserts so counters remain
    shared and race-safe across concurrent application workers.
    """
    if limit < 1 or window_seconds < 1:
        raise ValueError("Rate-limit settings must be positive.")

    settings = get_settings()
    message = f"{scope}:{identity.strip().lower()}".encode("utf-8")
    key = hmac.new(
        settings.app_secret_key.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_seconds)
    table = AuthRateLimitBucket.__table__
    dialect = db.get_bind().dialect.name

    if dialect == "postgresql":
        statement = pg_insert(table)
    elif dialect == "sqlite":
        statement = sqlite_insert(table)
    else:
        raise RuntimeError(
            "Authentication throttling requires PostgreSQL or SQLite."
        )

    expired = table.c.window_started_at <= cutoff
    statement = statement.values(
        bucket_key=key,
        window_started_at=now,
        request_count=1,
    ).on_conflict_do_update(
        index_elements=[table.c.bucket_key],
        set_={
            "window_started_at": case(
                (expired, now), else_=table.c.window_started_at
            ),
            "request_count": case(
                (expired, 1), else_=table.c.request_count + 1
            ),
        },
    ).returning(table.c.request_count)

    result = db.execute(
        statement.returning(table.c.request_count, table.c.window_started_at)
    ).one()
    request_count, window_started_at = result
    db.commit()

    if request_count > limit:
        if window_started_at.tzinfo is None:
            window_started_at = window_started_at.replace(tzinfo=timezone.utc)
        elapsed = (now - window_started_at).total_seconds()
        retry_after = max(1, ceil(window_seconds - elapsed))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def cleanup_expired_auth_rate_limit_buckets(
    db: Session,
    *,
    older_than: datetime,
    limit: int = 500,
) -> int:
    """Delete a bounded batch of old throttle rows and return its row count."""
    if not 1 <= limit <= 1000:
        raise ValueError("Cleanup batch limit must be between 1 and 1000.")
    if older_than.tzinfo is None or older_than.utcoffset() is None:
        raise ValueError("Cleanup cutoff must be timezone-aware.")

    table = AuthRateLimitBucket.__table__
    keys = db.scalars(
        select(table.c.bucket_key)
        .where(table.c.window_started_at < older_than)
        .order_by(table.c.window_started_at.asc())
        .limit(limit)
    ).all()
    if not keys:
        return 0

    result = db.execute(delete(table).where(table.c.bucket_key.in_(keys)))
    db.commit()
    return max(0, result.rowcount or 0)
