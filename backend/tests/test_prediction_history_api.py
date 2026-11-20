"""Authenticated API tests for prediction-history privacy controls."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.catalog import Disease
from app.models.prediction import (
    Prediction,
    PredictionConsentEvent,
    PredictionResult,
    SkinImageAnalysis,
)
from app.models.user import User

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def _register(client: TestClient, email: str) -> tuple[str, User]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPass123!"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    db = TestingSessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        return token, user
    finally:
        db.close()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _prediction(user_id, *, modality="text", input_text=None) -> Prediction:
    db = TestingSessionLocal()
    try:
        item = Prediction(
            user_id=user_id,
            modality=modality,
            status="completed",
            input_text=input_text,
            input_storage_consent=input_text is not None,
        )
        db.add(item)
        if input_text is not None:
            db.add(
                PredictionConsentEvent(
                    prediction_id=item.id,
                    purpose="prediction_history",
                    action="granted",
                    policy_version="history-v1",
                    captured_at=datetime.now(timezone.utc),
                )
            )
        db.commit()
        db.refresh(item)
        return item
    finally:
        db.close()


@pytest.fixture()
def client():
    """Create an isolated database and authenticated API test client."""
    Base.metadata.create_all(bind=engine)

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
    Base.metadata.drop_all(bind=engine)


def test_history_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/predictions/history").status_code == 401


def test_history_is_scoped_to_authenticated_user_and_hides_health_text(
    client: TestClient,
) -> None:
    token_a, user_a = _register(client, "history-a@example.com")
    _, user_b = _register(client, "history-b@example.com")
    own = _prediction(user_a.id, input_text="private symptom narrative")
    _prediction(user_b.id, input_text="another private narrative")

    response = client.get(
        "/api/v1/predictions/history", headers=_headers(token_a)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(own.id)
    assert "input_text" not in body["items"][0]
    assert "private symptom narrative" not in response.text


def test_history_rejects_invalid_pagination(client: TestClient) -> None:
    token, _ = _register(client, "history-page@example.com")
    response = client.get(
        "/api/v1/predictions/history?limit=0",
        headers=_headers(token),
    )
    assert response.status_code == 422


def test_user_can_revoke_text_history_consent(client: TestClient) -> None:
    token, user = _register(client, "revoke@example.com")
    item = _prediction(user.id, input_text="private symptom narrative")
    db = TestingSessionLocal()
    try:
        disease = Disease(
            code="TEST_DISEASE",
            name="Test Condition",
            is_active=True,
        )
        db.add(disease)
        db.flush()
        db.add(
            PredictionResult(
                prediction_id=item.id,
                disease_id=disease.id,
                rank=1,
                probability=0.25,
                explanation="private explanation",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/v1/predictions/history/{item.id}/revoke-consent",
        headers=_headers(token),
    )
    assert response.status_code == 200
    assert response.json()["consent_revoked"] is True
    db = TestingSessionLocal()
    try:
        stored = db.get(Prediction, item.id)
        assert stored is not None
        assert stored.input_text is None
        assert stored.input_storage_consent is False
        assert db.scalar(
            select(PredictionResult).where(
                PredictionResult.prediction_id == item.id
            )
        ) is None
        event = db.scalar(
            select(PredictionConsentEvent).where(
                PredictionConsentEvent.prediction_id == item.id
            )
        )
        assert event is not None and event.action == "revoked"
    finally:
        db.close()


def test_user_cannot_revoke_another_users_history(client: TestClient) -> None:
    token, _ = _register(client, "not-owner@example.com")
    _, owner = _register(client, "owner@example.com")
    item = _prediction(owner.id, input_text="private text")

    response = client.post(
        f"/api/v1/predictions/history/{item.id}/revoke-consent",
        headers=_headers(token),
    )
    assert response.status_code == 404


def test_user_can_delete_own_text_history(client: TestClient) -> None:
    token, user = _register(client, "delete-own@example.com")
    item = _prediction(user.id)
    response = client.delete(
        f"/api/v1/predictions/history/{item.id}",
        headers=_headers(token),
    )
    assert response.status_code == 204
    db = TestingSessionLocal()
    try:
        assert db.get(Prediction, item.id) is None
    finally:
        db.close()


def test_user_cannot_delete_another_users_history(client: TestClient) -> None:
    token, _ = _register(client, "delete-not-owner@example.com")
    _, owner = _register(client, "delete-owner@example.com")
    item = _prediction(owner.id)
    response = client.delete(
        f"/api/v1/predictions/history/{item.id}",
        headers=_headers(token),
    )
    assert response.status_code == 404


def test_image_history_delete_is_blocked_until_object_cleanup_exists(
    client: TestClient,
) -> None:
    token, user = _register(client, "image-delete@example.com")
    item = _prediction(user.id, modality="skin_image")
    db = TestingSessionLocal()
    try:
        db.add(
            SkinImageAnalysis(
                prediction_id=item.id,
                object_key="private/test-image",
                content_type="image/jpeg",
                image_sha256="a" * 64,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.delete(
        f"/api/v1/predictions/history/{item.id}",
        headers=_headers(token),
    )
    assert response.status_code == 409
    assert "object-storage cleanup" in response.json()["detail"]
