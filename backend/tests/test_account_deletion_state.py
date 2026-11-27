"""State-reconciliation tests for the account deletion worker."""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - register ORM metadata
from app.db.base import Base
from app.models.account_deletion import AccountDeletionRequest
from app.models.prediction import Prediction, SkinImageAnalysis
from app.models.user import User
from app.workers.account_deletion import process_deletion_request

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=engine, expire_on_commit=False)


class NoopStorage:
    def __init__(self):
        self.deleted = []

    def delete_private(self, object_key):
        self.deleted.append(object_key)


def test_unknown_image_storage_state_is_retained_for_manual_reconciliation():
    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="unknown-image-state@example.test",
            password_hash="test-only-hash",
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
            object_key="private/unknown-state.jpg",
            content_type="image/jpeg",
            image_sha256="f" * 64,
            storage_status="pending_upload",
        )
        db.add(image)
        db.commit()

        request_id = request.id
        prediction_id = prediction.id
        image_id = image.id
        storage = NoopStorage()

        assert process_deletion_request(db, request_id, storage) is False

        db.expire_all()
        stored_request = db.get(AccountDeletionRequest, request_id)
        assert stored_request is not None
        assert stored_request.status == "pending"
        assert stored_request.last_error_code == "image_storage_state_requires_reconciliation"
        assert db.get(Prediction, prediction_id) is not None
        stored_image = db.get(SkinImageAnalysis, image_id)
        assert stored_image is not None
        assert stored_image.storage_status == "pending_upload"
        assert storage.deleted == []
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_account_deletion_refuses_to_erase_an_active_account():
    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="active-account-delete@example.test",
            password_hash="test-only-hash",
            role="patient",
            is_active=True,
        )
        db.add(user)
        db.flush()
        request = AccountDeletionRequest(user_id=user.id, status="processing")
        db.add(request)
        db.commit()

        assert process_deletion_request(db, request.id, NoopStorage()) is False
        db.refresh(request)
        assert request.status == "failed"
        assert request.last_error_code == "account_state_requires_manual_review"
        assert db.get(User, user.id).is_active is True
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_account_deletion_retries_recent_retention_pending_image_immediately():
    """Account erasure must not wait for the retention worker's retry lease."""
    Base.metadata.create_all(bind=engine)
    db = Session()
    try:
        user = User(
            email="retention-pending-erasure@example.test",
            password_hash="test-only-hash",
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
            object_key="private/recent-retention-pending.jpg",
            content_type="image/jpeg",
            image_sha256="b" * 64,
            storage_status="deletion_pending",
            deletion_requested_at=datetime.now(timezone.utc),
        )
        db.add(image)
        db.commit()

        request_id = request.id
        prediction_id = prediction.id
        storage = NoopStorage()

        assert process_deletion_request(db, request_id, storage) is True

        db.expire_all()
        stored_request = db.get(AccountDeletionRequest, request_id)
        assert stored_request is not None and stored_request.status == "completed"
        assert db.get(Prediction, prediction_id) is None
        assert storage.deleted == ["private/recent-retention-pending.jpg"]
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

