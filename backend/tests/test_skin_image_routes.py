"""Regression tests for static skin-image review routes."""

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
