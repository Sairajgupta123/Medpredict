"""Image retention lifecycle tests using a retryable fake private store."""

from datetime import datetime, timedelta, timezone
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


def test_processing_and_history_consents_are_independent_and_revocable(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        has_active_skin_image_consent,
        record_skin_image_consent_decision,
    )

    user, prediction = _owned_image_history(db_session)
    # Processing permission does not imply permission to retain an image.
    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_processing",
        action="granted",
        policy_version="image-processing-v1",
    )
    assert has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_processing"
    )
    assert not has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )

    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_history",
        action="granted",
        policy_version="image-history-v1",
    )
    assert has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )

    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_history",
        action="revoked",
        policy_version="image-history-v1",
    )
    assert not has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )
    assert has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_processing"
    )



def test_retention_expiry_requires_separate_image_history_consent(
    db_session: Session,
) -> None:
    from app.services.prediction_history import set_skin_image_retention_expiry

    user, prediction = _owned_image_history(db_session)
    with pytest.raises(HTTPException) as error:
        set_skin_image_retention_expiry(
            db_session,
            user.id,
            prediction.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            policy_version="image-retention-v1",
        )
    assert error.value.status_code == 409


def test_expired_image_query_only_returns_expired_stored_objects(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        list_expired_skin_image_records,
        record_skin_image_consent_decision,
        set_skin_image_retention_expiry,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_history",
        action="granted",
        policy_version="image-history-v1",
    )
    expiry = datetime.now(timezone.utc) + timedelta(days=2)
    image = set_skin_image_retention_expiry(
        db_session,
        user.id,
        prediction.id,
        expires_at=expiry,
        policy_version="image-retention-v1",
    )
    assert image.retention_expires_at is not None
    assert image.retention_policy_version == "image-retention-v1"
    assert list_expired_skin_image_records(
        db_session, as_of=expiry - timedelta(seconds=1)
    ) == []
    due = list_expired_skin_image_records(db_session, as_of=expiry + timedelta(seconds=1))
    assert [item.id for item in due] == [image.id]


def test_retention_expiry_requires_timezone_and_future_timestamp(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        record_skin_image_consent_decision,
        set_skin_image_retention_expiry,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_history",
        action="granted",
        policy_version="image-history-v1",
    )
    with pytest.raises(HTTPException) as error:
        set_skin_image_retention_expiry(
            db_session,
            user.id,
            prediction.id,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None),
            policy_version="image-retention-v1",
        )
    assert error.value.status_code == 422


def test_history_consent_revocation_clears_assigned_reviewer_and_audits(
    db_session: Session,
) -> None:
    from app.models.prediction import SkinImageReviewEvent
    from app.models.reviewer_scope import CatalogReviewerScope
    from app.services.prediction_history import (
        record_skin_image_consent_decision,
        revoke_skin_image_history_consent,
    )

    owner, prediction = _owned_image_history(db_session)
    reviewer = User(
        id=uuid4(), email=f"{uuid4().hex}@example.test",
        password_hash="test-only-password-hash", role="reviewer",
        is_active=True, email_verified=True,
    )
    db_session.add(reviewer)
    db_session.flush()
    record_skin_image_consent_decision(
        db_session, owner.id, prediction.id,
        purpose="skin_image_history", action="granted",
        policy_version="image-history-v1",
    )
    image = db_session.scalar(select(SkinImageAnalysis).where(
        SkinImageAnalysis.prediction_id == prediction.id
    ))
    assert image is not None
    image.review_status = "assigned"
    image.assigned_reviewer_id = reviewer.id
    image.assigned_by = owner.id
    image.assigned_at = datetime.now(timezone.utc)
    scope = CatalogReviewerScope(
        reviewer_id=reviewer.id, scope_type="skin_image",
        scope_key=str(prediction.id), granted_by=owner.id,
        grant_reason="Owner authorized exact image review.",
    )
    db_session.add(scope)
    db_session.commit()

    revoke_skin_image_history_consent(
        db_session, owner.id, prediction.id,
        image_storage=FakePrivateStorage(), policy_version="image-history-v1",
    )
    db_session.refresh(image)
    db_session.refresh(scope)
    assert image.review_status == "pending"
    assert image.assigned_reviewer_id is None
    assert image.assigned_by is None
    assert image.assigned_at is None
    assert scope.revoked_at is not None
    event = db_session.scalar(select(SkinImageReviewEvent).where(
        SkinImageReviewEvent.prediction_id == prediction.id,
        SkinImageReviewEvent.event_type == "unassigned",
        SkinImageReviewEvent.assigned_reviewer_id == reviewer.id,
    ))
    assert event is not None and event.actor_id == owner.id
    assert "revoked image-history consent" in event.reason


def test_owner_history_deletion_clears_assigned_reviewer_and_audits(
    db_session: Session,
) -> None:
    from app.models.prediction import SkinImageReviewEvent
    from app.models.reviewer_scope import CatalogReviewerScope

    owner, prediction = _owned_image_history(db_session)
    reviewer = User(
        id=uuid4(), email=f"{uuid4().hex}@example.test",
        password_hash="test-only-password-hash", role="reviewer",
        is_active=True, email_verified=True,
    )
    db_session.add(reviewer)
    db_session.flush()
    image = db_session.scalar(select(SkinImageAnalysis).where(
        SkinImageAnalysis.prediction_id == prediction.id
    ))
    assert image is not None
    image.review_status = "assigned"
    image.assigned_reviewer_id = reviewer.id
    image.assigned_by = owner.id
    image.assigned_at = datetime.now(timezone.utc)
    scope = CatalogReviewerScope(
        reviewer_id=reviewer.id, scope_type="skin_image",
        scope_key=str(prediction.id), granted_by=owner.id,
        grant_reason="Owner authorized exact image review.",
    )
    db_session.add(scope)
    db_session.commit()

    delete_user_history_item(
        db_session, owner.id, prediction.id, image_storage=FakePrivateStorage(),
    )
    event = db_session.scalar(select(SkinImageReviewEvent).where(
        SkinImageReviewEvent.prediction_id == prediction.id,
        SkinImageReviewEvent.event_type == "unassigned",
        SkinImageReviewEvent.assigned_reviewer_id == reviewer.id,
    ))
    assert event is not None and event.actor_id == owner.id
    assert "owner deleted image history" in event.reason
    assert db_session.get(Prediction, prediction.id) is None


def test_image_history_consent_revocation_deletes_object_before_revoking(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        has_active_skin_image_consent,
        record_skin_image_consent_decision,
        revoke_skin_image_history_consent,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_history",
        action="granted",
        policy_version="image-history-v1",
    )
    storage = FakePrivateStorage()
    revoked = revoke_skin_image_history_consent(
        db_session,
        user.id,
        prediction.id,
        image_storage=storage,
        policy_version="image-history-v1",
    )
    image = db_session.scalar(
        select(SkinImageAnalysis).where(
            SkinImageAnalysis.prediction_id == prediction.id
        )
    )
    assert revoked.id == prediction.id
    assert image is not None and image.storage_status == "deleted"
    assert storage.deleted == ["skin-images/opaque-key.jpg"]
    assert not has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )


def test_image_history_consent_remains_active_until_failed_delete_is_retried(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        has_active_skin_image_consent,
        record_skin_image_consent_decision,
        revoke_skin_image_history_consent,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_history",
        action="granted",
        policy_version="image-history-v1",
    )
    from app.models.prediction import SkinImageReviewEvent
    from app.models.reviewer_scope import CatalogReviewerScope

    reviewer = User(
        id=uuid4(), email=f"{uuid4().hex}@example.test",
        password_hash="test-only-password-hash", role="reviewer",
        is_active=True, email_verified=True,
    )
    db_session.add(reviewer)
    db_session.flush()
    image = db_session.scalar(select(SkinImageAnalysis).where(
        SkinImageAnalysis.prediction_id == prediction.id
    ))
    assert image is not None
    image.review_status = "assigned"
    image.assigned_reviewer_id = reviewer.id
    image.assigned_by = user.id
    image.assigned_at = datetime.now(timezone.utc)
    scope = CatalogReviewerScope(
        reviewer_id=reviewer.id, scope_type="skin_image",
        scope_key=str(prediction.id), granted_by=user.id,
        grant_reason="Owner authorized exact image review.",
    )
    db_session.add(scope)
    db_session.commit()

    storage = FakePrivateStorage(fail_once=True)
    with pytest.raises(HTTPException) as error:
        revoke_skin_image_history_consent(
            db_session,
            user.id,
            prediction.id,
            image_storage=storage,
            policy_version="image-history-v1",
        )
    assert error.value.status_code == 503
    assert has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )
    image = db_session.scalar(
        select(SkinImageAnalysis).where(
            SkinImageAnalysis.prediction_id == prediction.id
        )
    )
    assert image is not None and image.storage_status == "deletion_pending"
    assert image.review_status == "pending"
    assert image.assigned_reviewer_id is None
    assert image.assigned_by is None
    assert image.assigned_at is None
    db_session.refresh(scope)
    assert scope.revoked_at is not None
    unassigned = db_session.scalar(select(SkinImageReviewEvent).where(
        SkinImageReviewEvent.prediction_id == prediction.id,
        SkinImageReviewEvent.event_type == "unassigned",
        SkinImageReviewEvent.assigned_reviewer_id == reviewer.id,
    ))
    assert unassigned is not None and unassigned.actor_id == user.id

    revoke_skin_image_history_consent(
        db_session,
        user.id,
        prediction.id,
        image_storage=storage,
        policy_version="image-history-v1",
    )
    assert not has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )
    assert storage.deleted == ["skin-images/opaque-key.jpg"]


def test_retention_purge_retries_pending_object_deletion(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        purge_expired_skin_image_records,
        record_skin_image_consent_decision,
        set_skin_image_retention_expiry,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session,
        user.id,
        prediction.id,
        purpose="skin_image_history",
        action="granted",
        policy_version="image-history-v1",
    )
    expiry = datetime.now(timezone.utc) + timedelta(days=1)
    image = set_skin_image_retention_expiry(
        db_session,
        user.id,
        prediction.id,
        expires_at=expiry,
        policy_version="image-retention-v1",
    )
    storage = FakePrivateStorage(fail_once=True)

    first = purge_expired_skin_image_records(
        db_session, image_storage=storage, as_of=expiry + timedelta(seconds=1)
    )
    assert first == {"processed": 1, "deleted": 0, "failed": 1}
    db_session.refresh(image)
    assert image.storage_status == "deletion_pending"

    second = purge_expired_skin_image_records(
        db_session, image_storage=storage, as_of=expiry + timedelta(seconds=2)
    )
    assert second == {"processed": 1, "deleted": 1, "failed": 0}
    db_session.refresh(image)
    assert image.storage_status == "deleted"
    assert image.retention_expires_at is None
    assert db_session.get(Prediction, prediction.id) is not None
    assert storage.deleted == ["skin-images/opaque-key.jpg"]


def test_retention_purge_revokes_history_consent_and_keeps_audit_rows(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        has_active_skin_image_consent,
        purge_expired_skin_image_records,
        record_skin_image_consent_decision,
        set_skin_image_retention_expiry,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session, user.id, prediction.id,
        purpose="skin_image_history", action="granted",
        policy_version="image-history-v1",
    )
    expiry = datetime.now(timezone.utc) + timedelta(minutes=1)
    image = set_skin_image_retention_expiry(
        db_session, user.id, prediction.id,
        expires_at=expiry, policy_version="retention-policy-v2",
    )
    storage = FakePrivateStorage()
    summary = purge_expired_skin_image_records(
        db_session, image_storage=storage, as_of=expiry + timedelta(seconds=1),
    )

    assert summary == {"processed": 1, "deleted": 1, "failed": 0}
    db_session.refresh(image)
    assert image.storage_status == "deleted"
    assert image.retention_expires_at is None
    assert db_session.get(Prediction, prediction.id) is not None
    assert not has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )
    events = list(db_session.scalars(
        select(PredictionConsentEvent)
        .where(
            PredictionConsentEvent.prediction_id == prediction.id,
            PredictionConsentEvent.purpose == "skin_image_history",
        )
        .order_by(PredictionConsentEvent.captured_at, PredictionConsentEvent.id)
    ).all())
    assert [event.action for event in events] == ["granted", "revoked"]
    assert events[-1].policy_version == "retention-policy-v2"
    assert storage.deleted == ["skin-images/opaque-key.jpg"]

    # A later scheduled run must ignore the completed record and keep its
    # single revocation event rather than processing or deleting it again.
    second_summary = purge_expired_skin_image_records(
        db_session, image_storage=storage, as_of=expiry + timedelta(hours=1),
    )
    assert second_summary == {"processed": 0, "deleted": 0, "failed": 0}
    assert storage.deleted == ["skin-images/opaque-key.jpg"]
    assert len(events) == 2


def test_retention_expiry_clears_assignment_and_audits_reviewer_access(
    db_session: Session,
) -> None:
    from app.models.prediction import SkinImageReviewEvent
    from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
    from app.services.prediction_history import (
        purge_expired_skin_image_records,
        record_skin_image_consent_decision,
        set_skin_image_retention_expiry,
    )

    owner, prediction = _owned_image_history(db_session)
    reviewer = User(
        id=uuid4(),
        email=f"{uuid4().hex}@example.test",
        password_hash="test-only-password-hash",
        role="reviewer",
        is_active=True,
        email_verified=True,
    )
    db_session.add(reviewer)
    db_session.flush()
    record_skin_image_consent_decision(
        db_session, owner.id, prediction.id,
        purpose="skin_image_history", action="granted",
        policy_version="image-history-v1",
    )
    expiry = datetime.now(timezone.utc) + timedelta(minutes=1)
    image = set_skin_image_retention_expiry(
        db_session, owner.id, prediction.id,
        expires_at=expiry, policy_version="retention-policy-v2",
    )
    image.review_status = "assigned"
    image.assigned_reviewer_id = reviewer.id
    image.assigned_by = owner.id
    image.assigned_at = datetime.now(timezone.utc)
    scope = CatalogReviewerScope(
        reviewer_id=reviewer.id,
        scope_type="skin_image",
        scope_key=str(prediction.id),
        granted_by=owner.id,
        grant_reason="Owner authorized this exact image review.",
    )
    db_session.add(scope)
    db_session.commit()

    summary = purge_expired_skin_image_records(
        db_session,
        image_storage=FakePrivateStorage(),
        as_of=expiry + timedelta(seconds=1),
    )

    assert summary == {"processed": 1, "deleted": 1, "failed": 0}
    db_session.refresh(image)
    db_session.refresh(scope)
    assert image.storage_status == "deleted"
    assert image.review_status == "pending"
    assert image.assigned_reviewer_id is None
    assert image.assigned_by is None
    assert image.assigned_at is None
    assert scope.revoked_at is not None
    unassignment = db_session.scalar(
        select(SkinImageReviewEvent).where(
            SkinImageReviewEvent.prediction_id == prediction.id,
            SkinImageReviewEvent.event_type == "unassigned",
            SkinImageReviewEvent.assigned_reviewer_id == reviewer.id,
        )
    )
    assert unassignment is not None
    assert unassignment.actor_id == owner.id
    assert "retention period expired" in unassignment.reason
    scope_event = db_session.scalar(
        select(CatalogReviewerScopeEvent).where(
            CatalogReviewerScopeEvent.scope_id == scope.id,
            CatalogReviewerScopeEvent.event_type == "revoked",
        )
    )
    assert scope_event is not None


def test_retention_purge_does_not_revoke_consent_when_object_delete_fails(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        has_active_skin_image_consent,
        purge_expired_skin_image_records,
        record_skin_image_consent_decision,
        set_skin_image_retention_expiry,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session, user.id, prediction.id,
        purpose="skin_image_history", action="granted",
        policy_version="image-history-v1",
    )
    expiry = datetime.now(timezone.utc) + timedelta(minutes=1)
    image = set_skin_image_retention_expiry(
        db_session, user.id, prediction.id,
        expires_at=expiry, policy_version="retention-policy-v2",
    )
    storage = FakePrivateStorage(fail_once=True)
    summary = purge_expired_skin_image_records(
        db_session, image_storage=storage, as_of=expiry + timedelta(seconds=1),
    )
    db_session.refresh(image)
    events = list(db_session.scalars(
        select(PredictionConsentEvent)
        .where(
            PredictionConsentEvent.prediction_id == prediction.id,
            PredictionConsentEvent.purpose == "skin_image_history",
        )
        .order_by(PredictionConsentEvent.captured_at, PredictionConsentEvent.id)
    ).all())
    assert summary == {"processed": 1, "deleted": 0, "failed": 1}
    assert image.storage_status == "deletion_pending"
    # PostgreSQL returns this TIMESTAMP WITHOUT TIME ZONE value as naive UTC.
    assert image.retention_expires_at == expiry.replace(tzinfo=None)
    assert [event.action for event in events] == ["granted"]
    assert has_active_skin_image_consent(
        db_session, prediction.id, purpose="skin_image_history"
    )

@pytest.mark.parametrize("limit", [0, -1, 501])
def test_expired_image_query_rejects_unbounded_limits_before_query(
    db_session: Session, limit: int
) -> None:
    from app.services.prediction_history import list_expired_skin_image_records

    with pytest.raises(ValueError, match="between 1 and 500"):
        list_expired_skin_image_records(
            db_session, as_of=datetime.now(timezone.utc), limit=limit
        )


def test_expired_image_query_rejects_naive_cutoff_before_query(
    db_session: Session,
) -> None:
    from app.services.prediction_history import list_expired_skin_image_records

    with pytest.raises(ValueError, match="include a timezone"):
        list_expired_skin_image_records(
            db_session, as_of=datetime.now(timezone.utc).replace(tzinfo=None)
        )

def test_retention_purge_does_not_duplicate_prior_history_consent_revocation(
    db_session: Session,
) -> None:
    from app.services.prediction_history import (
        purge_expired_skin_image_records,
        record_skin_image_consent_decision,
        set_skin_image_retention_expiry,
    )

    user, prediction = _owned_image_history(db_session)
    record_skin_image_consent_decision(
        db_session, user.id, prediction.id,
        purpose="skin_image_history", action="granted",
        policy_version="image-history-v1",
    )
    expiry = datetime.now(timezone.utc) + timedelta(minutes=1)
    image = set_skin_image_retention_expiry(
        db_session, user.id, prediction.id,
        expires_at=expiry, policy_version="retention-policy-v2",
    )
    record_skin_image_consent_decision(
        db_session, user.id, prediction.id,
        purpose="skin_image_history", action="revoked",
        policy_version="owner-revocation-v1",
    )

    storage = FakePrivateStorage()
    summary = purge_expired_skin_image_records(
        db_session, image_storage=storage, as_of=expiry + timedelta(seconds=1),
    )

    assert summary == {"processed": 1, "deleted": 1, "failed": 0}
    db_session.refresh(image)
    assert image.storage_status == "deleted"
    events = list(db_session.scalars(
        select(PredictionConsentEvent)
        .where(
            PredictionConsentEvent.prediction_id == prediction.id,
            PredictionConsentEvent.purpose == "skin_image_history",
        )
        .order_by(PredictionConsentEvent.captured_at, PredictionConsentEvent.id)
    ).all())
    assert [event.action for event in events] == ["granted", "revoked"]
    assert events[-1].policy_version == "owner-revocation-v1"
    assert storage.deleted == ["skin-images/opaque-key.jpg"]
