"""Tests for public disease and symptom catalog endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app import models  # noqa: F401 - register ORM metadata
from app.models.catalog import Disease, Symptom

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
    """Create a fresh in-memory catalog database for each test."""
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


def test_symptom_catalog_returns_only_active_approved_items(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                Symptom(
                    code="SYM_FEVER",
                    name="Fever",
                    is_active=True,
                    review_status="approved",
                    reviewed_by="reviewer-test",
                    reviewed_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ),
                ),
                Symptom(
                    code="SYM_COUGH",
                    name="Cough",
                    is_active=True,
                    review_status="draft",
                ),
                Symptom(
                    code="SYM_INTERNAL",
                    name="Internal Retired",
                    is_active=True,
                    review_status="retired",
                    reviewed_by="reviewer-test",
                    reviewed_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ),
                ),
                Symptom(
                    code="SYM_INACTIVE",
                    name="Inactive Approved",
                    is_active=False,
                    review_status="approved",
                    reviewed_by="reviewer-test",
                    reviewed_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/catalog/symptoms")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["name"] for item in body["items"]] == ["Fever"]


def test_symptom_catalog_searches_approved_items_by_name_and_code(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                Symptom(
                    code="SYM_FEVER",
                    name="Fever",
                    is_active=True,
                    review_status="approved",
                    reviewed_by="reviewer-test",
                    reviewed_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ),
                ),
                Symptom(
                    code="SYM_COUGH",
                    name="Cough",
                    is_active=True,
                    review_status="approved",
                    reviewed_by="reviewer-test",
                    reviewed_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    by_name = client.get("/api/v1/catalog/symptoms", params={"q": "fev"})
    by_code = client.get("/api/v1/catalog/symptoms", params={"q": "SYM_COUGH"})
    assert [item["name"] for item in by_name.json()["items"]] == ["Fever"]
    assert [item["name"] for item in by_code.json()["items"]] == ["Cough"]


def test_symptom_cannot_be_approved_without_reviewer_audit(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(
            Symptom(
                code="SYM_UNREVIEWED",
                name="Unreviewed",
                is_active=True,
                review_status="approved",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_disease_catalog_paginates(client: TestClient) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                Disease(code="DIS_B", name="Beta Condition", is_active=True),
                Disease(code="DIS_A", name="Alpha Condition", is_active=True),
                Disease(code="DIS_C", name="Gamma Condition", is_active=True),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/v1/catalog/diseases",
        params={"limit": 2, "offset": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert [item["name"] for item in body["items"]] == [
        "Beta Condition",
        "Gamma Condition",
    ]


def test_catalog_validates_pagination(client: TestClient) -> None:
    assert client.get(
        "/api/v1/catalog/symptoms",
        params={"limit": 0},
    ).status_code == 422
    assert client.get(
        "/api/v1/catalog/diseases",
        params={"limit": 101},
    ).status_code == 422
