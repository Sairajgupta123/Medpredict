"""Password recovery token lifecycle helpers."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.password_reset import PasswordResetToken
from app.models.user import User


def _token_digest(raw_token: str) -> str:
    """Return a fixed-length digest; raw recovery tokens are never persisted."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_password_reset_token(
    db: Session,
    user: User,
    *,
    expires_in_minutes: int = 30,
) -> str:
    """Issue a random reset token and persist only its SHA-256 digest.

    The caller owns the transaction and must commit before attempting delivery.
    Existing unused tokens are invalidated so only the newest link remains valid.
    """
    if expires_in_minutes < 1:
        raise ValueError("Password reset token lifetime must be positive.")
    if not user.is_active:
        raise ValueError("Inactive accounts cannot receive password reset tokens.")

    now = datetime.now(timezone.utc)
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    raw_token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_token_digest(raw_token),
            expires_at=now + timedelta(minutes=expires_in_minutes),
        )
    )
    db.flush()
    return raw_token


def consume_password_reset_token(db: Session, raw_token: str) -> User | None:
    """Atomically consume a valid token and return its active account once."""
    if not raw_token or len(raw_token) > 256:
        return None

    token_hash = _token_digest(raw_token)
    now = datetime.now(timezone.utc)
    token = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash
        )
    )
    if token is None:
        return None

    claimed = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == token.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        return None

    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    return user
