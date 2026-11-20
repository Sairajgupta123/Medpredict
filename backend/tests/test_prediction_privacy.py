"""Database-level privacy invariants for prediction history."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - register ORM metadata
from app.db.base import Base
from app.models.prediction import Prediction, PredictionConsentEvent
from app.models.user import User


@pytest.fixture()
def db_session():
    """Provide an isolated in-memory database with the complete ORM schema."""
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


def _user() -> User:
    return User(
        id=uuid4(),
        email=f"{uuid4().hex}@example.test",
        password_hash="test-only-password-hash",
        is_active=True,
        email_verified=False,
    )


def test_prediction_history_defaults_to_no_storage_consent(db_session: Session) -> None:
    prediction = Prediction(modality="text")
    db_session.add(prediction)
    db_session.commit()
    db_session.refresh(prediction)

    assert prediction.input_storage_consent is False
    assert prediction.input_text is None


def test_database_rejects_symptom_text_without_storage_consent(
    db_session: Session,
) -> None:
    db_session.add(_user())
    prediction = Prediction(
        modality="text",
        input_text="private symptom description",
        input_storage_consent=False,
    )
    db_session.add(prediction)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_consented_history_can_record_a_versioned_consent_event(
    db_session: Session,
) -> None:
    prediction = Prediction(
        modality="text",
        input_text="user-approved history text",
        input_storage_consent=True,
    )
    db_session.add(prediction)
    db_session.flush()
    event = PredictionConsentEvent(
        prediction_id=prediction.id,
        purpose="prediction_history",
        action="granted",
        policy_version="history-v1",
    )
    db_session.add(event)
    db_session.commit()

    stored = db_session.scalar(
        select(PredictionConsentEvent).where(
            PredictionConsentEvent.prediction_id == prediction.id
        )
    )
    assert stored is not None
    assert stored.action == "granted"
    assert stored.policy_version == "history-v1"


def test_consent_event_rejects_unknown_action(db_session: Session) -> None:
    prediction = Prediction(modality="text")
    db_session.add(prediction)
    db_session.flush()
    db_session.add(
        PredictionConsentEvent(
            prediction_id=prediction.id,
            action="maybe",
            policy_version="history-v1",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
