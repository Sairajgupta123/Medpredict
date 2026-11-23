"""Regression tests for static skin-image review routes."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - register ORM metadata
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.models.prediction import (
    Prediction,
    PredictionConsentEvent,
    SkinImageAnalysis,
    SkinImageReviewEvent,
)
from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent


test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def _admin_headers() -> dict[str, str]:
    db = TestingSessionLocal()
    try:
        admin = User(
            email=f"skin-review-admin-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="admin",
        )
        db.add(admin)
        db.commit()
        token = create_access_token(admin.id)
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def _user_headers(role: str) -> dict[str, str]:
    db = TestingSessionLocal()
    try:
        user = User(
            email=f"skin-review-{role}-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role=role,
        )
        db.add(user)
        db.commit()
        token = create_access_token(user.id)
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def test_static_review_queue_and_audit_routes_are_not_shadowed(
    client: TestClient,
) -> None:
    headers = _admin_headers()

    queue = client.get("/api/v1/skin-images/review/queue", headers=headers)
    audit = client.get("/api/v1/skin-images/review/audit", headers=headers)

    assert queue.status_code == 200
    assert queue.json() == []
    assert audit.status_code == 200
    assert audit.json() == []


def test_owner_image_route_rejects_non_uuid_path_segment(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/skin-images/not-a-uuid",
        headers=_admin_headers(),
    )
    assert response.status_code == 404


def test_patient_cannot_access_reviewer_queue_or_audit(
    client: TestClient,
) -> None:
    headers = _user_headers("patient")

    queue = client.get("/api/v1/skin-images/review/queue", headers=headers)
    audit = client.get("/api/v1/skin-images/review/audit", headers=headers)

    assert queue.status_code == 403
    assert audit.status_code == 403



def test_revoked_review_consent_blocks_reviewer_image_even_with_stale_scope(
    client: TestClient,
) -> None:
    """A leftover scope grant must never override the latest consent decision."""
    db = TestingSessionLocal()
    try:
        administrator = User(
            email=f"skin-review-owner-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="admin",
        )
        reviewer = User(
            email=f"skin-review-verified-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        db.add_all([administrator, reviewer])
        db.flush()

        prediction = Prediction(
            user_id=administrator.id,
            modality="skin_image",
            status="pending",
        )
        db.add(prediction)
        db.flush()
        image_record = SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key="private/test-image",
            content_type="image/png",
            image_sha256="0" * 64,
            storage_status="stored",
            review_status="assigned",
            assigned_reviewer_id=reviewer.id,
            assigned_by=administrator.id,
        )
        db.add(image_record)
        consent_time = datetime.now(timezone.utc)
        db.add_all([
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_processing",
                action="granted",
                policy_version="v1",
                captured_at=consent_time,
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_review",
                action="granted",
                policy_version="v1",
                captured_at=consent_time,
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_review",
                action="revoked",
                policy_version="v1",
                captured_at=consent_time + timedelta(seconds=1),
            ),
            CatalogReviewerScope(
                reviewer_id=reviewer.id,
                scope_type="skin_image",
                scope_key=str(prediction.id),
                granted_by=administrator.id,
                grant_reason="Assigned for a controlled image review.",
            ),
        ])
        db.commit()
        prediction_id = str(prediction.id)
        reviewer_uuid = reviewer.id
        token = create_access_token(reviewer.id)
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {token}"}
    queue = client.get("/api/v1/skin-images/review/queue", headers=headers)
    image = client.get(
        f"/api/v1/skin-images/review/{prediction_id}/image",
        headers=headers,
    )
    events = client.get(
        f"/api/v1/skin-images/review/{prediction_id}/events",
        headers=headers,
    )
    assignment = client.post(
        f"/api/v1/skin-images/review/{prediction_id}/assign",
        headers=_admin_headers(),
        json={
            "reviewer_id": str(reviewer_uuid),
            "reason": "Reassignment must respect revoked consent.",
        },
    )
    decision = client.post(
        f"/api/v1/skin-images/review/{prediction_id}/decision",
        headers=headers,
        json={
            "outcome": "capture_adequate",
            "reason": "Decision must respect revoked consent.",
        },
    )

    assert queue.status_code == 200
    assert queue.json() == []
    assert image.status_code == 403
    assert "consent" in image.json()["detail"].lower()
    assert events.status_code == 403
    assert "consent" in events.json()["detail"].lower()
    assert assignment.status_code == 403
    assert "consent" in assignment.json()["detail"].lower()
    assert decision.status_code == 403
    assert "consent" in decision.json()["detail"].lower()



def test_owner_revocation_atomically_disables_reviewer_scope(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        owner = User(
            email=f"skin-image-owner-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="patient",
        )
        reviewer = User(
            email=f"skin-image-reviewer-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        db.add_all([owner, reviewer])
        db.flush()
        prediction = Prediction(
            user_id=owner.id,
            modality="skin_image",
            status="pending",
        )
        db.add(prediction)
        db.flush()
        db.add_all([
            SkinImageAnalysis(
                prediction_id=prediction.id,
                object_key="private/revocation-test",
                content_type="image/png",
                image_sha256="1" * 64,
                storage_status="stored",
                review_status="assigned",
                assigned_reviewer_id=reviewer.id,
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_review",
                action="granted",
                policy_version="v1",
                captured_at=datetime.now(timezone.utc),
            ),
            CatalogReviewerScope(
                reviewer_id=reviewer.id,
                scope_type="skin_image",
                scope_key=str(prediction.id),
                granted_by=owner.id,
                grant_reason="Owner approved this exact image review.",
            ),
        ])
        db.commit()
        prediction_id = str(prediction.id)
        prediction_uuid = prediction.id
        owner_token = create_access_token(owner.id)
        reviewer_id = reviewer.id
    finally:
        db.close()

    response = client.post(
        f"/api/v1/skin-images/{prediction_id}/revoke-review-consent",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert response.status_code == 200
    assert response.json()["reviewer_access_revoked"] is True

    db = TestingSessionLocal()
    try:
        scope = db.query(CatalogReviewerScope).filter_by(
            reviewer_id=reviewer_id,
            scope_type="skin_image",
            scope_key=prediction_id,
        ).one()
        scope_event = db.query(CatalogReviewerScopeEvent).filter_by(
            scope_id=scope.id,
            event_type="revoked",
        ).one()
        revoked_consent = db.query(PredictionConsentEvent).filter_by(
            prediction_id=prediction_uuid,
            purpose="skin_image_review",
            action="revoked",
        ).one()
        assert revoked_consent is not None
        assert scope.revoked_at is not None
        assert scope.revoked_by is not None
        assert scope.revoke_reason
        assert scope_event.reason
    finally:
        db.close()

def test_reassignment_revokes_previous_reviewers_access(
    client: TestClient,
) -> None:
    """Reassignment transfers access and revokes the previous reviewer's scope."""
    db = TestingSessionLocal()
    try:
        administrator = User(
            email=f"skin-reassign-admin-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="admin",
        )
        previous_reviewer = User(
            email=f"skin-reassign-old-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        new_reviewer = User(
            email=f"skin-reassign-new-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        db.add_all([administrator, previous_reviewer, new_reviewer])
        db.flush()

        prediction = Prediction(
            user_id=administrator.id,
            modality="skin_image",
            status="pending",
        )
        db.add(prediction)
        db.flush()
        captured_at = datetime.now(timezone.utc)
        image_record = SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key="private/reassignment-test",
            content_type="image/png",
            image_sha256="2" * 64,
            storage_status="stored",
            review_status="assigned",
            assigned_reviewer_id=previous_reviewer.id,
            assigned_by=administrator.id,
        )
        db.add_all([
            image_record,
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_processing",
                action="granted",
                policy_version="v1",
                captured_at=captured_at,
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_review",
                action="granted",
                policy_version="v1",
                captured_at=captured_at,
            ),
            CatalogReviewerScope(
                reviewer_id=previous_reviewer.id,
                scope_type="skin_image",
                scope_key=str(prediction.id),
                granted_by=administrator.id,
                grant_reason="Initial reviewer access approved.",
            ),
            CatalogReviewerScope(
                reviewer_id=new_reviewer.id,
                scope_type="skin_image",
                scope_key=str(prediction.id),
                granted_by=administrator.id,
                grant_reason="Replacement reviewer access approved.",
            ),
        ])
        db.commit()
        prediction_id = str(prediction.id)
        prediction_uuid = prediction.id
        previous_id = previous_reviewer.id
        new_id = new_reviewer.id
        admin_token = create_access_token(administrator.id)
        previous_token = create_access_token(previous_reviewer.id)
        new_token = create_access_token(new_reviewer.id)
    finally:
        db.close()

    assignment = client.post(
        f"/api/v1/skin-images/review/{prediction_id}/assign",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "reviewer_id": str(new_id),
            "reason": "Transfer to the replacement reviewer.",
        },
    )
    assert assignment.status_code == 200
    assert assignment.json()["reviewer_id"] == str(new_id)

    previous_headers = {"Authorization": f"Bearer {previous_token}"}
    previous_queue = client.get(
        "/api/v1/skin-images/review/queue",
        headers=previous_headers,
    )
    previous_image = client.get(
        f"/api/v1/skin-images/review/{prediction_id}/image",
        headers=previous_headers,
    )
    previous_events = client.get(
        f"/api/v1/skin-images/review/{prediction_id}/events",
        headers=previous_headers,
    )

    new_headers = {"Authorization": f"Bearer {new_token}"}
    new_queue = client.get(
        "/api/v1/skin-images/review/queue",
        headers=new_headers,
    )
    new_events = client.get(
        f"/api/v1/skin-images/review/{prediction_id}/events",
        headers=new_headers,
    )

    assert previous_queue.status_code == 200
    assert previous_queue.json() == []
    assert previous_image.status_code == 404
    assert previous_events.status_code == 404
    assert new_queue.status_code == 200
    assert [item["prediction_id"] for item in new_queue.json()] == [prediction_id]
    assert new_events.status_code == 200

    db = TestingSessionLocal()
    try:
        old_scope = db.query(CatalogReviewerScope).filter_by(
            reviewer_id=previous_id,
            scope_type="skin_image",
            scope_key=prediction_id,
        ).one()
        old_scope_event = db.query(CatalogReviewerScopeEvent).filter_by(
            scope_id=old_scope.id,
            event_type="revoked",
        ).one()
        current_image = db.query(SkinImageAnalysis).filter_by(
            prediction_id=prediction_uuid,
        ).one()
        assert old_scope.revoked_at is not None
        assert old_scope.revoke_reason
        assert old_scope_event.reason
        assert current_image.assigned_reviewer_id == new_id
    finally:
        db.close()

def test_review_decision_is_terminal_and_audited_once(
    client: TestClient,
) -> None:
    """A completed technical review cannot be overwritten by a second decision."""
    db = TestingSessionLocal()
    try:
        administrator = User(
            email=f"skin-decision-admin-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="admin",
        )
        reviewer = User(
            email=f"skin-decision-reviewer-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        db.add_all([administrator, reviewer])
        db.flush()
        prediction = Prediction(
            user_id=administrator.id,
            modality="skin_image",
            status="pending",
        )
        db.add(prediction)
        db.flush()
        captured_at = datetime.now(timezone.utc)
        db.add_all([
            SkinImageAnalysis(
                prediction_id=prediction.id,
                object_key="private/decision-test",
                content_type="image/png",
                image_sha256="3" * 64,
                storage_status="stored",
                review_status="assigned",
                assigned_reviewer_id=reviewer.id,
                assigned_by=administrator.id,
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_processing",
                action="granted",
                policy_version="v1",
                captured_at=captured_at,
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_review",
                action="granted",
                policy_version="v1",
                captured_at=captured_at,
            ),
            CatalogReviewerScope(
                reviewer_id=reviewer.id,
                scope_type="skin_image",
                scope_key=str(prediction.id),
                granted_by=administrator.id,
                grant_reason="Reviewer approved for technical assessment.",
            ),
        ])
        db.commit()
        prediction_id = str(prediction.id)
        prediction_uuid = prediction.id
        reviewer_token = create_access_token(reviewer.id)
        reviewer_uuid = reviewer.id
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {reviewer_token}"}
    endpoint = f"/api/v1/skin-images/review/{prediction_id}/decision"
    first = client.post(
        endpoint,
        headers=headers,
        json={
            "outcome": "capture_adequate",
            "reason": "Image capture quality is adequate.",
        },
    )
    second = client.post(
        endpoint,
        headers=headers,
        json={
            "outcome": "unable_to_assess",
            "reason": "Attempt to overwrite completed review.",
        },
    )

    assert first.status_code == 200
    assert first.json()["review_status"] == "reviewed"
    assert first.json()["review_outcome"] == "capture_adequate"
    assert first.json()["clinical_interpretation_performed"] is False
    assert first.json()["disease_prediction_performed"] is False
    assert second.status_code == 409

    db = TestingSessionLocal()
    try:
        image_record = db.query(SkinImageAnalysis).filter_by(
            prediction_id=prediction_uuid,
        ).one()
        review_events = db.query(SkinImageReviewEvent).filter_by(
            prediction_id=prediction_uuid,
            event_type="reviewed",
        ).all()
        assert image_record.assigned_reviewer_id == reviewer_uuid
        assert image_record.review_status == "reviewed"
        assert image_record.review_outcome == "capture_adequate"
        assert len(review_events) == 1
        assert review_events[0].actor_id == reviewer_uuid
        assert review_events[0].reason == "Image capture quality is adequate."
    finally:
        db.close()
