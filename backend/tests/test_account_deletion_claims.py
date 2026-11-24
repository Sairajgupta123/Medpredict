"""Concurrency-claim tests for the account deletion worker."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - register ORM metadata
from app.db.base import Base
from app.models.account_deletion import AccountDeletionRequest
from app.models.user import User
from app.workers.account_deletion import _claim_deletion_request

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=engine, expire_on_commit=False)


def test_only_one_worker_can_claim_a_pending_deletion_request() -> None:
    Base.metadata.create_all(bind=engine)
    first = Session()
    second = Session()
    try:
        user = User(
            email="claim-test@example.com",
            password_hash="not-a-real-password-hash",
            role="patient",
            is_active=False,
        )
        first.add(user)
        first.flush()
        request = AccountDeletionRequest(user_id=user.id)
        first.add(request)
        first.commit()
        request_id = request.id

        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(hours=2)

        assert _claim_deletion_request(
            first, request_id, now=now, stale_before=stale_before
        ) is True
        assert _claim_deletion_request(
            second, request_id, now=now, stale_before=stale_before
        ) is False

        stored = second.scalar(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.id == request_id
            )
        )
        assert stored is not None
        assert stored.status == "processing"
        assert stored.attempts == 1
    finally:
        first.close()
        second.close()
        Base.metadata.drop_all(bind=engine)


def test_abandoned_processing_request_can_be_reclaimed() -> None:
    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="stale-claim-test@example.com",
            password_hash="not-a-real-password-hash",
            role="patient",
            is_active=False,
        )
        db.add(user)
        db.flush()
        now = datetime.now(timezone.utc)
        request = AccountDeletionRequest(
            user_id=user.id,
            status="processing",
            attempts=1,
            last_attempt_at=now - timedelta(hours=3),
        )
        db.add(request)
        db.commit()

        assert _claim_deletion_request(
            db,
            request.id,
            now=now,
            stale_before=now - timedelta(hours=2),
        ) is True
        db.refresh(request)
        assert request.status == "processing"
        assert request.attempts == 2
        assert request.last_attempt_at.replace(tzinfo=timezone.utc) == now
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)



def test_processing_request_without_attempt_timestamp_is_recovered() -> None:
    """Legacy processing rows without a lease timestamp must not remain stuck forever."""
    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="missing-lease-claim-test@example.com",
            password_hash="not-a-real-password-hash",
            role="patient",
            is_active=False,
        )
        db.add(user)
        db.flush()
        now = datetime.now(timezone.utc)
        request = AccountDeletionRequest(
            user_id=user.id,
            status="processing",
            attempts=1,
            last_attempt_at=None,
        )
        db.add(request)
        db.commit()

        assert _claim_deletion_request(
            db,
            request.id,
            now=now,
            stale_before=now - timedelta(hours=2),
        ) is True
        db.refresh(request)
        assert request.status == "processing"
        assert request.attempts == 2
        assert request.last_attempt_at.replace(tzinfo=timezone.utc) == now
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
