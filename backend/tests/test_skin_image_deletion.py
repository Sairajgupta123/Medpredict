"""Image retention lifecycle tests using a retryable fake private store."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.models.prediction import Prediction, PredictionConsentEvent, SkinImageAnalysis
from app.models.user import User
from app.services.prediction_history import delete_user_history_item


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


class FakePrivateStorage:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.deleted: list[str] = []

    def delete_private(self, object_key: str) -> None:
        if self.fail_once:
            self.fail_once = False
            raise OSError("simulated storage outage")
        self.deleted.append(object_key)


def _owned_image_history(db: Session) -> tuple[User, Prediction]:
    user = User(
        id=uuid4(),
        email=f"{uuid4().hex}@example.test",
        password_hash="test-only-password-hash",
        is_active=True,
        email_verified=False,
    )
    prediction = Prediction(
        user_id=user.id,
        modality="skin_image",
        status="completed",
    )
    db.add_all([user, prediction])
    db.flush()
    db.add(
        SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key="skin-images/opaque-key.jpg",
            content_type="image/jpeg",
            image_sha256="a" * 64,
            storage_status="stored",
        )
    )
    db.commit()
    return user, prediction


def test_image_processing_consent_is_a_separate_audited_purpose(db_session: Session) -> None:
    prediction = Prediction(modality="skin_image")
    db_session.add(prediction)
    db_session.flush()
    db_session.add(
        PredictionConsentEvent(
            prediction_id=prediction.id,
            purpose="skin_image_processing",
            action="granted",
            policy_version="image-processing-v1",
        )
    )
    db_session.commit()
    event = db_session.scalar(
        select(PredictionConsentEvent).where(
            PredictionConsentEvent.prediction_id == prediction.id
        )
    )
    assert event is not None
    assert event.purpose == "skin_image_processing"


def test_image_deletion_failure_keeps_durable_retry_marker(db_session: Session) -> None:
    user, prediction = _owned_image_history(db_session)
    storage = FakePrivateStorage(fail_once=True)

    with pytest.raises(HTTPException) as error:
        delete_user_history_item(
            db_session, user.id, prediction.id, image_storage=storage
        )
    assert error.value.status_code == 503
    db_session.expire_all()
    retained = db_session.get(Prediction, prediction.id)
    image = db_session.scalar(
        select(SkinImageAnalysis).where(
            SkinImageAnalysis.prediction_id == prediction.id
        )
    )
    assert retained is not None
    assert image is not None and image.storage_status == "deletion_pending"

    delete_user_history_item(
        db_session, user.id, prediction.id, image_storage=storage
    )
    assert storage.deleted == ["skin-images/opaque-key.jpg"]
    assert db_session.get(Prediction, prediction.id) is None


def test_image_history_without_storage_adapter_remains_blocked(db_session: Session) -> None:
    user, prediction = _owned_image_history(db_session)
    with pytest.raises(HTTPException) as error:
        delete_user_history_item(db_session, user.id, prediction.id)
    assert error.value.status_code == 409
    assert db_session.get(Prediction, prediction.id) is not None