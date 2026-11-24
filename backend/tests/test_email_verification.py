"""Email verification token lifecycle tests using isolated SQLite storage."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.email_verification import (
    consume_email_verification_token,
    invalidate_email_verification_token,
    issue_email_verification_token,
)
from app.db.base import Base
from app.models.email_verification import EmailVerificationToken
from app.models.user import User


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _active_user(db_session) -> User:
    user = User(email="verify@example.com", password_hash="test-hash")
    db_session.add(user)
    db_session.commit()
    return user


def test_verification_token_persists_only_digest(db_session) -> None:
    user = _active_user(db_session)
    raw_token = issue_email_verification_token(db_session, user)
    db_session.commit()

    stored = db_session.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    assert stored is not None
    assert stored.token_hash != raw_token
    assert len(stored.token_hash) == 64
    assert stored.used_at is None


def test_verification_token_is_single_use(db_session) -> None:
    user = _active_user(db_session)
    raw_token = issue_email_verification_token(db_session, user)
    db_session.commit()

    assert consume_email_verification_token(db_session, raw_token).id == user.id
    assert consume_email_verification_token(db_session, raw_token) is None


def test_expired_verification_token_cannot_be_consumed(db_session) -> None:
    user = _active_user(db_session)
    raw_token = issue_email_verification_token(db_session, user)
    stored = db_session.scalar(select(EmailVerificationToken))
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert consume_email_verification_token(db_session, raw_token) is None


def test_new_verification_token_invalidates_previous_token(db_session) -> None:
    user = _active_user(db_session)
    first = issue_email_verification_token(db_session, user)
    second = issue_email_verification_token(db_session, user)
    db_session.commit()

    assert consume_email_verification_token(db_session, first) is None
    assert consume_email_verification_token(db_session, second).id == user.id


def test_failed_delivery_token_can_be_invalidated(db_session) -> None:
    user = _active_user(db_session)
    raw_token = issue_email_verification_token(db_session, user)
    db_session.commit()

    assert invalidate_email_verification_token(db_session, raw_token) is True
    db_session.commit()
    assert consume_email_verification_token(db_session, raw_token) is None
    assert invalidate_email_verification_token(db_session, raw_token) is False


@pytest.mark.parametrize(
    ("is_active", "email_verified"),
    [(False, False), (True, True)],
)
def test_only_active_unverified_accounts_can_receive_tokens(
    db_session, is_active: bool, email_verified: bool
) -> None:
    user = User(
        email="ineligible@example.com",
        password_hash="test-hash",
        is_active=is_active,
        email_verified=email_verified,
    )
    db_session.add(user)
    db_session.commit()

    with pytest.raises(ValueError, match="Only active, unverified"):
        issue_email_verification_token(db_session, user)


def test_invalid_token_sizes_are_rejected(db_session) -> None:
    assert consume_email_verification_token(db_session, "") is None
    assert consume_email_verification_token(db_session, "x" * 257) is None
    assert invalidate_email_verification_token(db_session, "") is False
    assert invalidate_email_verification_token(db_session, "x" * 257) is False


def test_non_positive_token_lifetime_is_rejected(db_session) -> None:
    user = _active_user(db_session)
    with pytest.raises(ValueError, match="lifetime must be positive"):
        issue_email_verification_token(db_session, user, expires_in_minutes=0)
