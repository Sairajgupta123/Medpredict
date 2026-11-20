"""Password hashing and signed access-token utilities."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hasher = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hasher.hash("not-a-real-user-password")


def hash_password(password: str) -> str:
    """Hash a password with the recommended Argon2 configuration."""
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its stored hash."""
    try:
        return password_hasher.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: UUID) -> str:
    """Create a short-lived signed JWT for a user UUID."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": expires_at,
        "type": "access",
        "iss": "medipredict-api",
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> UUID | None:
    """Validate a signed access token and return its user UUID."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.app_secret_key,
            algorithms=["HS256"],
            issuer="medipredict-api",
            options={"require": ["exp", "iat", "sub", "iss", "type"]},
        )
        if payload.get("type") != "access":
            return None
        return UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        return None
