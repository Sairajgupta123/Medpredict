"""Password reset token lifecycle tests using isolated SQLite storage."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app import models  # noqa: F401 - register ORM metadata
from app.core.password_reset import (
    consume_password_reset_token,
    issue_password_reset_token,
)
from app.models.password_reset import PasswordResetToken
from app.models.user import User


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _active_user(db_session) -> User:
    user = User(email="reset@example.com", password_hash="test-hash")
    db_session.add(user)
    db_session.commit()
    return user


def test_reset_token_is_stored_as_digest_not_raw_value(db_session) -> None:
    user = _active_user(db_session)

    raw_token = issue_password_reset_token(db_session, user)
    db_session.commit()

    stored = db_session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id
        )
    )
    assert stored is not None
    assert stored.token_hash != raw_token
    assert len(stored.token_hash) == 64
    assert stored.used_at is None


def test_valid_reset_token_can_be_consumed_only_once(db_session) -> None:
    user = _active_user(db_session)
    raw_token = issue_password_reset_token(db_session, user)
    db_session.commit()

    first_use = consume_password_reset_token(db_session, raw_token)
    second_use = consume_password_reset_token(db_session, raw_token)

    assert first_use is not None
    assert first_use.id == user.id
    assert second_use is None


def test_expired_reset_token_cannot_be_consumed(db_session) -> None:
    user = _active_user(db_session)
    raw_token = issue_password_reset_token(db_session, user)
    stored = db_session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id
        )
    )
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert consume_password_reset_token(db_session, raw_token) is None


def test_issuing_new_token_invalidates_previous_token(db_session) -> None:
    user = _active_user(db_session)
    first_token = issue_password_reset_token(db_session, user)
    second_token = issue_password_reset_token(db_session, user)
    db_session.commit()

    assert consume_password_reset_token(db_session, first_token) is None
    assert consume_password_reset_token(db_session, second_token) is not None


def test_inactive_account_cannot_receive_reset_token(db_session) -> None:
    user = User(
        email="inactive-reset@example.com",
        password_hash="test-hash",
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()

    with pytest.raises(ValueError, match="Inactive accounts"):
        issue_password_reset_token(db_session, user)


def test_blank_or_oversized_reset_token_is_rejected(db_session) -> None:
    assert consume_password_reset_token(db_session, "") is None
    assert consume_password_reset_token(db_session, "x" * 257) is None
