"""Tests for public disease and symptom catalog endpoints."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - register ORM metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.catalog import Disease, DiseaseSymptom, Symptom

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


def _approved_disease(code: str, name: str) -> Disease:
    """Build a disease fixture with required reviewer audit metadata."""
    return Disease(
        code=code,
        name=name,
        is_active=True,
        review_status="approved",
        reviewed_by="reviewer-test",
        reviewed_at=datetime.now(timezone.utc),
    )


def _approved_symptom(code: str, name: str) -> Symptom:
    """Build a symptom fixture with the required approval audit metadata."""
    return Symptom(
        code=code,
        name=name,
        is_active=True,
        review_status="approved",
        reviewed_by="reviewer-test",
        reviewed_at=datetime.now(timezone.utc),
    )


def test_symptom_catalog_returns_only_active_approved_items(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                _approved_symptom("SYM_FEVER", "Fever"),
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
                    reviewed_at=datetime.now(timezone.utc),
                ),
                Symptom(
                    code="SYM_INACTIVE",
                    name="Inactive Approved",
                    is_active=False,
                    review_status="approved",
                    reviewed_by="reviewer-test",
                    reviewed_at=datetime.now(timezone.utc),
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
                _approved_symptom("SYM_FEVER", "Fever"),
                _approved_symptom("SYM_COUGH", "Cough"),
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
                _approved_disease("DIS_B", "Beta Condition"),
                _approved_disease("DIS_A", "Alpha Condition"),
                _approved_disease("DIS_C", "Gamma Condition"),
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

def test_disease_catalog_returns_only_active_approved_items(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                _approved_disease("DIS_APPROVED", "Approved Condition"),
                Disease(
                    code="DIS_DRAFT",
                    name="Draft Condition",
                    is_active=True,
                    review_status="draft",
                ),
                Disease(
                    code="DIS_RETIRED",
                    name="Retired Condition",
                    is_active=True,
                    review_status="retired",
                    reviewed_by="reviewer-test",
                    reviewed_at=datetime.now(timezone.utc),
                ),
                Disease(
                    code="DIS_INACTIVE",
                    name="Inactive Approved Condition",
                    is_active=False,
                    review_status="approved",
                    reviewed_by="reviewer-test",
                    reviewed_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/catalog/diseases")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["name"] for item in body["items"]] == ["Approved Condition"]


def test_disease_cannot_be_approved_without_reviewer_audit(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(
            Disease(
                code="DIS_UNREVIEWED",
                name="Unreviewed Condition",
                is_active=True,
                review_status="approved",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()

def _approved_link(disease: Disease, symptom: Symptom) -> DiseaseSymptom:
    """Build a disease-symptom association with reviewer audit metadata."""
    return DiseaseSymptom(
        disease_id=disease.id,
        symptom_id=symptom.id,
        relevance_weight=1.0,
        review_status="approved",
        reviewed_by="reviewer-test",
        reviewed_at=datetime.now(timezone.utc),
    )


def test_disease_symptom_endpoint_requires_approved_disease(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(
            Disease(
                code="DIS_DRAFT_LINK",
                name="Draft Disease",
                is_active=True,
                review_status="draft",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/catalog/diseases/DIS_DRAFT_LINK/symptoms")
    assert response.status_code == 404


def test_disease_symptom_endpoint_returns_only_approved_links_and_symptoms(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        disease = _approved_disease("DIS_LINKED", "Linked Disease")
        approved_symptom = _approved_symptom("SYM_LINKED", "Approved Symptom")
        draft_symptom = Symptom(
            code="SYM_DRAFT_LINK",
            name="Draft Symptom",
            is_active=True,
            review_status="draft",
        )
        retired_link_symptom = _approved_symptom(
            "SYM_UNREVIEWED_LINK", "Unreviewed Link Symptom"
        )
        db.add_all([disease, approved_symptom, draft_symptom, retired_link_symptom])
        db.flush()
        db.add_all(
            [
                _approved_link(disease, approved_symptom),
                _approved_link(disease, draft_symptom),
                DiseaseSymptom(
                    disease_id=disease.id,
                    symptom_id=retired_link_symptom.id,
                    relevance_weight=1.0,
                    review_status="draft",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/catalog/diseases/DIS_LINKED/symptoms")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symptom"]["name"] == "Approved Symptom"
    assert body[0]["relevance_weight"] == 1.0


def test_disease_symptom_link_cannot_be_approved_without_reviewer_audit(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        disease = _approved_disease("DIS_AUDIT", "Audit Disease")
        symptom = _approved_symptom("SYM_AUDIT", "Audit Symptom")
        db.add_all([disease, symptom])
        db.flush()
        db.add(
            DiseaseSymptom(
                disease_id=disease.id,
                symptom_id=symptom.id,
                review_status="approved",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()

