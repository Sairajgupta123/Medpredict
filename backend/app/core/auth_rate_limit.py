"""Database-backed throttling for authentication requests."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac

from fastapi import HTTPException, status
from sqlalchemy import case
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

    request_count = db.scalar(statement)
    db.commit()

    if request_count is not None and request_count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please try again later.",
            headers={"Retry-After": str(window_seconds)},
        )
