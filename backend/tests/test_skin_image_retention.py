"""Tests for bounded, retry-safe skin-image retention expiry."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - register ORM metadata
from app.db.base import Base
from app.models.prediction import (
    Prediction,
    PredictionConsentEvent,
    SkinImageAnalysis,
)
from app.models.user import User
from app.services.prediction_history import purge_expired_skin_image_records


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


class FakeImageStorage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []

    def delete_private(self, object_key: str) -> None:
        self.deleted.append(object_key)
        if self.fail:
            raise RuntimeError("simulated object-storage outage")


def _expired_image(db: Session) -> tuple[Prediction, SkinImageAnalysis]:
    user = User(
        email=f"{uuid4().hex}@example.test",
        password_hash="test-only-hash",
    )
    db.add(user)
    db.flush()

    prediction = Prediction(user_id=user.id, modality="skin_image")
    db.add(prediction)
    db.flush()

    image = SkinImageAnalysis(
        prediction_id=prediction.id,
        object_key=f"skin-images/{uuid4().hex}.jpg",
        content_type="image/jpeg",
        image_sha256="a" * 64,
        storage_status="stored",
        retention_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        retention_policy_version="image-history-v1",
    )
    db.add(image)
    db.add(
        PredictionConsentEvent(
            prediction_id=prediction.id,
            purpose="skin_image_history",
            action="granted",
            policy_version="image-history-v1",
        )
    )
    db.commit()
    db.refresh(image)
    return prediction, image


def test_expired_image_is_deleted_and_history_consent_is_revoked(
    db_session: Session,
) -> None:
    prediction, image = _expired_image(db_session)
    storage = FakeImageStorage()

    result = purge_expired_skin_image_records(
        db_session,
        image_storage=storage,
        as_of=datetime.now(timezone.utc),
        limit=10,
    )

    db_session.refresh(image)
    consent_events = list(
        db_session.scalars(
            select(PredictionConsentEvent).where(
                PredictionConsentEvent.prediction_id == prediction.id,
                PredictionConsentEvent.purpose == "skin_image_history",
            )
        ).all()
    )
    assert result == {"processed": 1, "deleted": 1, "failed": 0}
    assert storage.deleted == [image.object_key]
    assert image.storage_status == "deleted"
    assert image.retention_expires_at is None
    assert [event.action for event in consent_events] == ["granted", "revoked"]


def test_failed_expiry_keeps_retry_marker_and_does_not_revoke_consent(
    db_session: Session,
) -> None:
    prediction, image = _expired_image(db_session)
    original_expiry = image.retention_expires_at
    storage = FakeImageStorage(fail=True)

    result = purge_expired_skin_image_records(
        db_session,
        image_storage=storage,
        as_of=datetime.now(timezone.utc),
        limit=10,
    )

    db_session.refresh(image)
    consent_events = list(
        db_session.scalars(
            select(PredictionConsentEvent).where(
                PredictionConsentEvent.prediction_id == prediction.id,
                PredictionConsentEvent.purpose == "skin_image_history",
            )
        ).all()
    )
    assert result == {"processed": 1, "deleted": 0, "failed": 1}
    assert image.storage_status == "deletion_pending"
    assert image.retention_expires_at == original_expiry
    assert [event.action for event in consent_events] == ["granted"]
