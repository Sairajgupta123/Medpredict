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
from app.models.prediction import Prediction, PredictionConsentEvent, SkinImageAnalysis
from app.models.reviewer_scope import CatalogReviewerScope


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
        token = create_access_token(reviewer.id)
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {token}"}
    queue = client.get("/api/v1/skin-images/review/queue", headers=headers)
    image = client.get(
        f"/api/v1/skin-images/review/{prediction_id}/image",
        headers=headers,
    )

    assert queue.status_code == 200
    assert queue.json() == []
    assert image.status_code == 403
    assert "consent" in image.json()["detail"].lower()
