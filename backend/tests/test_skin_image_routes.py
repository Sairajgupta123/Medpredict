"""Regression tests for static skin-image review routes."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

from PIL import Image

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



def test_assigned_reviewer_image_retrieval_is_private_and_audited(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful image read requires active consent and creates an audit event."""
    from app.api.v1 import skin_images

    output = BytesIO()
    with Image.new("RGB", (256, 256), (110, 80, 70)) as source:
        source.save(output, format="PNG")
    image_bytes = output.getvalue()

    class FakePrivateStorage:
        def get_private(self, object_key: str) -> bytes:
            assert object_key == "private/reviewer-fetch-test"
            return image_bytes

    monkeypatch.setattr(
        skin_images,
        "build_skin_image_storage",
        lambda: FakePrivateStorage(),
    )

    db = TestingSessionLocal()
    try:
        owner = User(
            email=f"skin-fetch-owner-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="patient",
        )
        reviewer = User(
            email=f"skin-fetch-reviewer-{uuid4().hex}@example.test",
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
        captured_at = datetime.now(timezone.utc)
        image_record = SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key="private/reviewer-fetch-test",
            content_type="image/png",
            image_sha256=sha256(image_bytes).hexdigest(),
            storage_status="stored",
            review_status="assigned",
            assigned_reviewer_id=reviewer.id,
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
        reviewer_id = reviewer.id
        reviewer_token = create_access_token(reviewer.id)
    finally:
        db.close()

    response = client.get(
        f"/api/v1/skin-images/review/{prediction_id}/image",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )

    assert response.status_code == 200
    assert response.content == image_bytes
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "sandbox" in response.headers["content-security-policy"]

    db = TestingSessionLocal()
    try:
        access_events = db.query(SkinImageReviewEvent).filter_by(
            prediction_id=prediction_uuid,
            event_type="image_accessed",
        ).all()
        assert len(access_events) == 1
        assert str(access_events[0].actor_id) == str(reviewer_id)
        assert access_events[0].reason == "Authorized private image retrieval completed."
    finally:
        db.close()


def test_revoked_history_consent_blocks_owner_image_retrieval(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale owner consent grant cannot authorize image retrieval."""
    from app.api.v1 import skin_images

    def unexpected_storage():
        raise AssertionError("storage must not be accessed after consent revocation")

    monkeypatch.setattr(skin_images, "build_skin_image_storage", unexpected_storage)

    db = TestingSessionLocal()
    try:
        owner = User(
            email=f"skin-owner-revoked-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="patient",
        )
        db.add(owner)
        db.flush()
        prediction = Prediction(
            user_id=owner.id,
            modality="skin_image",
            status="pending",
        )
        db.add(prediction)
        db.flush()
        captured_at = datetime.now(timezone.utc)
        db.add_all([
            SkinImageAnalysis(
                prediction_id=prediction.id,
                object_key="private/owner-revoked-test",
                content_type="image/png",
                image_sha256="0" * 64,
                storage_status="stored",
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_history",
                action="granted",
                policy_version="v1",
                captured_at=captured_at,
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_history",
                action="revoked",
                policy_version="v1",
                captured_at=captured_at + timedelta(seconds=1),
            ),
        ])
        db.commit()
        prediction_id = str(prediction.id)
        owner_token = create_access_token(owner.id)
    finally:
        db.close()

    response = client.get(
        f"/api/v1/skin-images/{prediction_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert response.status_code == 403
    assert "image-history consent" in response.json()["detail"].lower()


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

    owner_status = client.get(
        f"/api/v1/skin-images/{prediction_id}/review-status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_status.status_code == 200
    assert owner_status.json()["status"] == "review_access_withdrawn"
    assert owner_status.json()["clinical_interpretation_performed"] is False
    assert owner_status.json()["disease_prediction_performed"] is False
    assert "reviewer_id" not in owner_status.json()
    assert "object_key" not in owner_status.json()

    # Repeating the same withdrawal must not append duplicate consent or scope
    # audit events, and must not claim that an already-revoked grant was active.
    repeated_response = client.post(
        f"/api/v1/skin-images/{prediction_id}/revoke-review-consent",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert repeated_response.status_code == 409
    assert "no active consent" in repeated_response.json()["detail"].lower()

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
        image_record = db.query(SkinImageAnalysis).filter_by(
            prediction_id=prediction_uuid,
        ).one()
        assert image_record.review_status == "pending"
        assert image_record.assigned_reviewer_id is None
        assert image_record.assigned_by is None
        assert image_record.assigned_at is None
        unassignment = db.query(SkinImageReviewEvent).filter_by(
            prediction_id=prediction_uuid,
            event_type="unassigned",
            assigned_reviewer_id=reviewer_id,
        ).one()
        assert "revoked human-review consent" in unassignment.reason
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
        assignment_events = db.query(SkinImageReviewEvent).filter_by(
            prediction_id=prediction_uuid,
        ).order_by(SkinImageReviewEvent.created_at.asc()).all()
        assert any(
            event.event_type == "unassigned"
            and event.assigned_reviewer_id == previous_id
            for event in assignment_events
        )
        assert any(
            event.event_type == "reassigned"
            and event.assigned_reviewer_id == new_id
            for event in assignment_events
        )
    finally:
        db.close()


def test_admin_can_recover_pending_image_after_reviewer_deactivation(
    client: TestClient,
) -> None:
    """A pending image can be safely assigned to a newly authorized reviewer."""
    admin_headers = _admin_headers()
    db = TestingSessionLocal()
    try:
        # The test helper creates exactly one administrator for this test.
        administrator = db.query(User).filter_by(role="admin").one()
        reviewer = User(
            email=f"skin-recovery-reviewer-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        db.add(reviewer)
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
                object_key="private/recovery-test",
                content_type="image/png",
                image_sha256="3" * 64,
                storage_status="stored",
                review_status="pending",
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
                grant_reason="Replacement reviewer explicitly authorized.",
            ),
        ])
        db.commit()
        prediction_id = str(prediction.id)
        reviewer_id = str(reviewer.id)
    finally:
        db.close()

    response = client.post(
        f"/api/v1/skin-images/review/{prediction_id}/assign",
        headers=admin_headers,
        json={
            "reviewer_id": reviewer_id,
            "reason": "Recover pending work after reviewer deactivation.",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["reviewer_id"] == reviewer_id
    assert response.json()["review_status"] == "assigned"

    replacement_reviewer_headers = {
        "Authorization": f"Bearer {create_access_token(UUID(reviewer_id))}"
    }
    replacement_queue = client.get(
        "/api/v1/skin-images/review/queue",
        headers=replacement_reviewer_headers,
    )
    assert replacement_queue.status_code == 200, replacement_queue.text
    assert any(
        item["prediction_id"] == prediction_id
        and item["review_status"] == "assigned"
        for item in replacement_queue.json()
    )

    db = TestingSessionLocal()
    try:
        image_record = db.query(SkinImageAnalysis).filter_by(
            prediction_id=UUID(prediction_id),
        ).one()
        assert image_record.review_status == "assigned"
        assert image_record.assigned_reviewer_id == UUID(reviewer_id)
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

def test_review_decision_rejects_invalid_outcome_and_short_reason(
    client: TestClient,
) -> None:
    """Invalid review payloads must not mutate the review record or audit trail."""
    db = TestingSessionLocal()
    try:
        administrator = User(
            email=f"skin-invalid-admin-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="admin",
        )
        reviewer = User(
            email=f"skin-invalid-reviewer-{uuid4().hex}@example.test",
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
                object_key="private/invalid-decision-test",
                content_type="image/png",
                image_sha256="4" * 64,
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
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {reviewer_token}"}
    endpoint = f"/api/v1/skin-images/review/{prediction_id}/decision"
    invalid_outcome = client.post(
        endpoint,
        headers=headers,
        json={
            "outcome": "diagnose_melanoma",
            "reason": "This outcome is not a supported technical review.",
        },
    )
    short_reason = client.post(
        endpoint,
        headers=headers,
        json={
            "outcome": "capture_adequate",
            "reason": "bad",
        },
    )

    assert invalid_outcome.status_code == 422
    assert short_reason.status_code == 422

    db = TestingSessionLocal()
    try:
        image_record = db.query(SkinImageAnalysis).filter_by(
            prediction_id=prediction_uuid,
        ).one()
        review_events = db.query(SkinImageReviewEvent).filter_by(
            prediction_id=prediction_uuid,
            event_type="reviewed",
        ).all()
        assert image_record.review_status == "assigned"
        assert image_record.review_outcome is None
        assert image_record.reviewed_at is None
        assert review_events == []
    finally:
        db.close()

def test_review_audit_is_scoped_and_pagination_is_bounded(
    client: TestClient,
) -> None:
    """Reviewers see only related events; admins can page through all events."""
    db = TestingSessionLocal()
    try:
        reviewer = User(
            email=f"skin-audit-reviewer-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        other_reviewer = User(
            email=f"skin-audit-other-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        administrator = User(
            email=f"skin-audit-admin-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="admin",
        )
        patient = User(
            email=f"skin-audit-patient-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="patient",
        )
        db.add_all([reviewer, other_reviewer, administrator, patient])
        db.flush()

        prediction_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
        image_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
        db.add_all([
            SkinImageReviewEvent(
                prediction_id=prediction_ids[0],
                image_analysis_id=image_ids[0],
                event_type="assigned",
                actor_id=administrator.id,
                assigned_reviewer_id=reviewer.id,
                reason="Assigned to the requesting reviewer.",
            ),
            SkinImageReviewEvent(
                prediction_id=prediction_ids[1],
                image_analysis_id=image_ids[1],
                event_type="reviewed",
                actor_id=reviewer.id,
                assigned_reviewer_id=other_reviewer.id,
                outcome="capture_adequate",
                reason="Reviewer acted on an assigned review.",
            ),
            SkinImageReviewEvent(
                prediction_id=prediction_ids[2],
                image_analysis_id=image_ids[2],
                event_type="assigned",
                actor_id=administrator.id,
                assigned_reviewer_id=other_reviewer.id,
                reason="Assigned only to another reviewer.",
            ),
            SkinImageReviewEvent(
                prediction_id=prediction_ids[3],
                image_analysis_id=image_ids[3],
                event_type="unassigned",
                actor_id=patient.id,
                assigned_reviewer_id=other_reviewer.id,
                reason="Owner withdrew human-review consent.",
            ),
        ])
        db.commit()
        reviewer_token = create_access_token(reviewer.id)
        admin_token = create_access_token(administrator.id)
    finally:
        db.close()

    reviewer_headers = {"Authorization": f"Bearer {reviewer_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    reviewer_audit = client.get(
        "/api/v1/skin-images/review/audit?limit=10&offset=0",
        headers=reviewer_headers,
    )
    admin_first_page = client.get(
        "/api/v1/skin-images/review/audit?limit=2&offset=0",
        headers=admin_headers,
    )
    admin_second_page = client.get(
        "/api/v1/skin-images/review/audit?limit=2&offset=2",
        headers=admin_headers,
    )
    admin_all_events = client.get(
        "/api/v1/skin-images/review/audit?limit=10&offset=0",
        headers=admin_headers,
    )
    invalid_limit = client.get(
        "/api/v1/skin-images/review/audit?limit=201",
        headers=admin_headers,
    )
    invalid_offset = client.get(
        "/api/v1/skin-images/review/audit?offset=-1",
        headers=admin_headers,
    )

    assert reviewer_audit.status_code == 200
    assert {item["prediction_id"] for item in reviewer_audit.json()} == {
        str(prediction_ids[0]),
        str(prediction_ids[1]),
    }
    assert len(reviewer_audit.json()) == 2
    assert admin_first_page.status_code == 200
    assert len(admin_first_page.json()) == 2
    assert admin_second_page.status_code == 200
    assert len(admin_second_page.json()) == 2
    assert admin_all_events.status_code == 200
    assert any(
        item["actor_role"] == "patient"
        and item["event_type"] == "unassigned"
        for item in admin_all_events.json()
    )
    assert invalid_limit.status_code == 422
    assert invalid_offset.status_code == 422
    for item in reviewer_audit.json():
        assert "object_key" not in item
        assert "patient_email" not in item
        assert "image_bytes" not in item

def test_skin_image_intake_requires_each_separate_consent(
    client: TestClient,
) -> None:
    """No image bytes are accepted unless all three purpose-specific grants exist."""
    headers = _user_headers("patient")
    response = client.post(
        "/api/v1/skin-images/intake",
        headers=headers,
        files={"image": ("lesion.png", b"not-a-real-image", "image/png")},
        data={
            "processing_consent": "true",
            "history_consent": "true",
            "review_consent": "false",
            "processing_policy_version": "processing-v1",
            "history_policy_version": "history-v1",
            "review_policy_version": "review-v1",
        },
    )

    assert response.status_code == 422
    assert "Separate image-processing" in response.json()["detail"]

def test_skin_image_model_status_reports_inference_unavailable(
    client: TestClient,
) -> None:
    """Clients must not present image intake as an active disease classifier."""
    response = client.get("/api/v1/skin-images/model-status")

    assert response.status_code == 200
    body = response.json()
    assert body["inference_available"] is False
    assert body["model_configured"] is False
    assert body["disease_prediction_performed"] is False
    assert body["clinical_validation_status"] == "not_established"
    assert body["human_review_required"] is True
    assert body["image_intake_configured"] is False
    assert body["image_retention_days"] is None
    assert "not configured" in body["message"]

def test_owner_review_status_is_private_and_reports_only_non_diagnostic_states(
    client: TestClient,
) -> None:
    """Owner status is scoped and never exposes reviewer, storage or diagnostic data."""
    db = TestingSessionLocal()
    try:
        owner = User(
            email=f"skin-status-owner-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="patient",
        )
        other_user = User(
            email=f"skin-status-other-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="patient",
        )
        reviewer = User(
            email=f"skin-status-reviewer-{uuid4().hex}@example.test",
            password_hash="test-only-hash",
            role="reviewer",
            is_active=True,
            email_verified=True,
        )
        db.add_all([owner, other_user, reviewer])
        db.flush()
        prediction = Prediction(
            user_id=owner.id,
            modality="skin_image",
            status="pending",
        )
        db.add(prediction)
        db.flush()
        captured_at = datetime.now(timezone.utc)
        image_record = SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key="private/owner-status-test",
            content_type="image/png",
            image_sha256="5" * 64,
            storage_status="stored",
            review_status="pending",
        )
        db.add(image_record)
        db.add_all([
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
        ])
        db.commit()
        prediction_id = str(prediction.id)
        owner_headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        other_headers = {"Authorization": f"Bearer {create_access_token(other_user.id)}"}
        reviewer_id = reviewer.id
        image_id = image_record.id
    finally:
        db.close()

    endpoint = f"/api/v1/skin-images/{prediction_id}/review-status"
    unauthenticated_view = client.get(endpoint)
    forbidden_owner_view = client.get(endpoint, headers=other_headers)
    malformed_reference = client.get(
        "/api/v1/skin-images/not-a-uuid/review-status",
        headers=owner_headers,
    )
    assert unauthenticated_view.status_code == 401
    assert forbidden_owner_view.status_code == 404
    assert malformed_reference.status_code == 404

    def assert_safe_status(expected: str) -> dict:
        response = client.get(endpoint, headers=owner_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["prediction_id"] == prediction_id
        assert body["status"] == expected
        assert body["clinical_interpretation_performed"] is False
        assert body["disease_prediction_performed"] is False
        assert not {
            "object_key", "image_bytes", "image_sha256", "assigned_reviewer_id",
            "reviewer_id", "reviewer_email", "review_outcome", "confidence",
            "predicted_class", "audit_events",
        }.intersection(body)
        return body

    assert_safe_status("awaiting_review")

    db = TestingSessionLocal()
    try:
        image_record = db.get(SkinImageAnalysis, image_id)
        assert image_record is not None
        image_record.review_status = "assigned"
        image_record.assigned_reviewer_id = reviewer_id
        image_record.assigned_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    assert_safe_status("assigned")

    db = TestingSessionLocal()
    try:
        image_record = db.get(SkinImageAnalysis, image_id)
        assert image_record is not None
        image_record.review_status = "reviewed"
        image_record.review_outcome = "capture_adequate"
        image_record.reviewed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    assert_safe_status("reviewed")

    db = TestingSessionLocal()
    try:
        image_record = db.get(SkinImageAnalysis, image_id)
        assert image_record is not None
        image_record.review_status = "unable_to_assess"
        image_record.review_outcome = "unable_to_assess"
        image_record.reviewed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
    assert_safe_status("unable_to_assess")

    db = TestingSessionLocal()
    try:
        image_record = db.get(SkinImageAnalysis, image_id)
        assert image_record is not None
        image_record.storage_status = "failed"
        db.commit()
    finally:
        db.close()
    assert_safe_status("submission_unavailable")

    db = TestingSessionLocal()
    try:
        image_record = db.get(SkinImageAnalysis, image_id)
        assert image_record is not None
        image_record.storage_status = "stored"
        db.add(PredictionConsentEvent(
            prediction_id=UUID(prediction_id),
            purpose="skin_image_review",
            action="revoked",
            policy_version="v1",
            captured_at=datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()
    assert_safe_status("review_access_withdrawn")

