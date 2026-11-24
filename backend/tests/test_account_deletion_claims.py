"""Concurrency-claim tests for the account deletion worker."""

from datetime import datetime, timedelta, timezone

import pytest

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

        first_token = _claim_deletion_request(
            first, request_id, now=now, stale_before=stale_before
        )
        assert first_token is not None
        assert _claim_deletion_request(
            second, request_id, now=now, stale_before=stale_before
        ) is None

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

        token = _claim_deletion_request(
            db,
            request.id,
            now=now,
            stale_before=now - timedelta(hours=2),
        )
        assert token is not None
        db.refresh(request)
        assert request.claim_token == token
        assert request.status == "processing"
        assert request.attempts == 2
        assert request.last_attempt_at.replace(tzinfo=timezone.utc) == now
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)



def test_reclaimed_deletion_request_rejects_previous_worker_token() -> None:
    from app.workers.account_deletion import DeletionClaimLost, _lock_owned_request

    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="fenced-claim-test@example.com",
            password_hash="not-a-real-password-hash",
            role="patient",
            is_active=False,
        )
        db.add(user)
        db.flush()
        now = datetime.now(timezone.utc)
        request = AccountDeletionRequest(user_id=user.id)
        db.add(request)
        db.commit()

        old_token = _claim_deletion_request(
            db, request.id, now=now, stale_before=now - timedelta(hours=2)
        )
        assert old_token is not None
        new_token = _claim_deletion_request(
            db,
            request.id,
            now=now + timedelta(hours=3),
            stale_before=now + timedelta(hours=1),
        )
        assert new_token is not None and new_token != old_token

        with pytest.raises(DeletionClaimLost):
            _lock_owned_request(db, request.id, old_token)
        assert _lock_owned_request(db, request.id, new_token) is not None
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

        token = _claim_deletion_request(
            db,
            request.id,
            now=now,
            stale_before=now - timedelta(hours=2),
        )
        assert token is not None
        db.refresh(request)
        assert request.claim_token == token
        assert request.status == "processing"
        assert request.attempts == 2
        assert request.last_attempt_at.replace(tzinfo=timezone.utc) == now
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)



class _FakePrivateStorage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []

    def delete_private(self, object_key: str) -> None:
        if self.fail:
            raise OSError("storage unavailable")
        self.deleted.append(object_key)


def test_account_deletion_erases_text_history_and_keeps_non_login_tombstone() -> None:
    from app.models.prediction import Prediction
    from app.workers.account_deletion import process_deletion_request

    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="erase-text@example.test",
            password_hash="test-only-password-hash",
            role="patient",
            is_active=False,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        prediction = Prediction(
            user_id=user.id,
            modality="text",
            status="completed",
        )
        request = AccountDeletionRequest(user_id=user.id, status="processing")
        db.add_all([prediction, request])
        db.commit()
        user_id = user.id
        request_id = request.id

        assert process_deletion_request(db, request_id, _FakePrivateStorage()) is True
        db.expire_all()
        tombstone = db.get(User, user_id)
        stored_request = db.get(AccountDeletionRequest, request_id)
        assert tombstone is not None
        assert tombstone.is_active is False
        assert tombstone.email == f"deleted+{user_id.hex}@invalid.local"
        assert tombstone.display_name is None
        assert tombstone.last_login_at is None
        assert db.get(Prediction, prediction.id) is None
        assert stored_request is not None and stored_request.status == "completed"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_account_deletion_storage_failure_keeps_health_rows_for_retry() -> None:
    from app.models.email_verification import EmailVerificationToken
    from app.models.password_reset import PasswordResetToken
    from app.models.prediction import (
        Prediction, SkinImageAnalysis, SkinImageReviewEvent,
    )
    from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
    from app.workers.account_deletion import process_deletion_request

    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="erase-image@example.test",
            password_hash="test-only-password-hash",
            role="patient",
            is_active=False,
        )
        db.add(user)
        db.flush()
        prediction = Prediction(
            user_id=user.id,
            modality="skin_image",
            status="review_required",
        )
        request = AccountDeletionRequest(user_id=user.id, status="processing")
        db.add_all([prediction, request])
        db.flush()
        image = SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key="private/opaque-image.jpg",
            content_type="image/jpeg",
            image_sha256="c" * 64,
            storage_status="stored",
        )
        db.add(image)
        reviewer = User(
            email="erase-reviewer@example.test",
            password_hash="test-only-password-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        db.add(reviewer)
        db.flush()
        image.review_status = "assigned"
        image.assigned_reviewer_id = reviewer.id
        image.assigned_by = user.id
        image.assigned_at = datetime.now(timezone.utc)
        scope = CatalogReviewerScope(
            reviewer_id=reviewer.id,
            scope_type="skin_image",
            scope_key=str(prediction.id),
            granted_by=user.id,
            grant_reason="Owner authorized exact image review.",
        )
        db.add(scope)
        now = datetime.now(timezone.utc)
        db.add_all([
            PasswordResetToken(
                user_id=user.id,
                token_hash="d" * 64,
                expires_at=now + timedelta(minutes=20),
            ),
            EmailVerificationToken(
                user_id=user.id,
                token_hash="e" * 64,
                expires_at=now + timedelta(minutes=20),
            ),
        ])
        db.commit()
        request_id = request.id
        scope_id = scope.id
        reviewer_id = reviewer.id
        prediction_id = prediction.id
        image_id = image.id

        assert process_deletion_request(
            db, request_id, _FakePrivateStorage(fail=True)
        ) is False
        db.expire_all()
        stored_request = db.get(AccountDeletionRequest, request_id)
        retained_prediction = db.get(Prediction, prediction_id)
        retained_image = db.get(SkinImageAnalysis, image_id)
        assert stored_request is not None and stored_request.status == "pending"
        assert db.scalar(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        ) is None
        assert db.scalar(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        ) is None
        assert retained_prediction is not None
        assert retained_image is not None
        assert retained_image.storage_status == "deletion_pending"
        assert retained_image.review_status == "pending"
        assert retained_image.assigned_reviewer_id is None
        revoked_scope = db.get(CatalogReviewerScope, scope_id)
        assert revoked_scope is not None and revoked_scope.revoked_at is not None
        assert revoked_scope.revoked_by == user.id
        scope_event = db.scalar(
            select(CatalogReviewerScopeEvent).where(
                CatalogReviewerScopeEvent.scope_id == scope_id,
                CatalogReviewerScopeEvent.event_type == "revoked",
            )
        )
        assert scope_event is not None
        assert scope_event.reviewer_id == reviewer_id
        assert scope_event.operator_id == user.id
        unassignment = db.scalar(
            select(SkinImageReviewEvent).where(
                SkinImageReviewEvent.prediction_id == prediction_id,
                SkinImageReviewEvent.event_type == "unassigned",
            )
        )
        assert unassignment is not None
        assert unassignment.actor_id == user.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
