"""Email verification token lifecycle helpers."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.email_verification import EmailVerificationToken
from app.models.user import User


def _digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_email_verification_token(
    db: Session, user: User, *, expires_in_minutes: int = 30
) -> str:
    """Issue a fresh token and invalidate earlier unused verification links."""
    if expires_in_minutes < 1:
        raise ValueError("Email verification token lifetime must be positive.")
    if user.email_verified or not user.is_active:
        raise ValueError("Only active, unverified accounts can request verification.")
    now = datetime.now(timezone.utc)
    db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(32)
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=_digest(raw_token),
            expires_at=now + timedelta(minutes=expires_in_minutes),
        )
    )
    db.flush()
    return raw_token


def invalidate_email_verification_token(db: Session, raw_token: str) -> bool:
    """Invalidate a token whose email delivery failed."""
    if not raw_token or len(raw_token) > 256:
        return False
    result = db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.token_hash == _digest(raw_token),
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def consume_email_verification_token(db: Session, raw_token: str) -> User | None:
    """Atomically consume a valid token and return its active account once."""
    if not raw_token or len(raw_token) > 256:
        return None
    now = datetime.now(timezone.utc)
    token = db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == _digest(raw_token)
        )
    )
    if token is None:
        return None
    claimed = db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.id == token.id,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        return None
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    return user
