"""Tests for the reviewed, source-backed medical knowledge API."""

from datetime import date, datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - register ORM metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.catalog import Disease
from app.models.knowledge import (
    CareRecommendation,
    MedicalReference,
    RecommendationReference,
)

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


def make_client():
    """Create a test client with an isolated in-memory database."""
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def close_client(client: TestClient) -> None:
    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_public_api_returns_only_approved_active_source_backed_guidance() -> None:
    client = make_client()
    try:
        db = TestingSessionLocal()
        disease = Disease(
            code="DIS_TEST",
            name="Test condition",
            is_active=True,
            review_status="approved",
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(disease)
        db.flush()
        approved_source = MedicalReference(
            title="Public health guidance",
            publisher="Example public health authority",
            url="https://example.org/guidance",
            evidence_type="public_guideline",
            version="2026",
            accessed_on=date.today(),
            review_status="approved",
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
        )
        draft_source = MedicalReference(
            title="Unreviewed draft",
            publisher="Example publisher",
            url="https://example.org/draft",
            evidence_type="draft",
            version="1",
            accessed_on=date.today(),
            review_status="draft",
        )
        db.add_all([approved_source, draft_source])
        db.flush()
        approved_item = CareRecommendation(
            disease_id=disease.id,
            code="CARE_GENERAL",
            version="1",
            locale="en",
            category="general_care",
            urgency="routine",
            title="General information",
            content="Discuss persistent symptoms with a qualified healthcare professional.",
            review_status="approved",
            is_active=True,
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
            references=[
                RecommendationReference(reference=approved_source),
                RecommendationReference(reference=draft_source),
            ],
        )
        unreviewed_item = CareRecommendation(
            disease_id=disease.id,
            code="CARE_DRAFT",
            version="1",
            locale="en",
            category="general_care",
            urgency="routine",
            title="Draft content",
            content="This must never be public.",
            review_status="draft",
            is_active=True,
            references=[RecommendationReference(reference=approved_source)],
        )
        approved_without_approved_source = CareRecommendation(
            disease_id=disease.id,
            code="CARE_NO_APPROVED_SOURCE",
            version="1",
            locale="en",
            category="general_care",
            urgency="routine",
            title="No approved source",
            content="This must remain unpublished.",
            review_status="approved",
            is_active=True,
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
            references=[RecommendationReference(reference=draft_source)],
        )
        inactive_item = CareRecommendation(
            disease_id=disease.id,
            code="CARE_INACTIVE",
            version="1",
            locale="en",
            category="general_care",
            urgency="routine",
            title="Inactive content",
            content="This must never be public.",
            review_status="approved",
            is_active=False,
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
            references=[RecommendationReference(reference=approved_source)],
        )
        db.add_all([
            approved_item,
            unreviewed_item,
            approved_without_approved_source,
            inactive_item,
        ])
        db.commit()
        db.close()

        response = client.get(
            "/api/v1/knowledge/diseases/DIS_TEST/recommendations"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["code"] == "CARE_GENERAL"
        assert len(body["items"][0]["references"]) == 1
        assert "not a diagnosis" in body["disclaimer"]
        assert "This must never be public." not in response.text
        assert "This must remain unpublished." not in response.text
    finally:
        close_client(client)


def test_knowledge_api_filters_locale_and_category() -> None:
    client = make_client()
    try:
        db = TestingSessionLocal()
        disease = Disease(
            code="DIS_FILTER",
            name="Filter condition",
            is_active=True,
            review_status="approved",
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(disease)
        db.flush()
        source = MedicalReference(
            title="Reviewed source",
            publisher="Example authority",
            url="https://example.org/reviewed",
            evidence_type="guideline",
            version="1",
            accessed_on=date.today(),
            review_status="approved",
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(source)
        db.flush()
        db.add_all(
            [
                CareRecommendation(
                    disease_id=disease.id, code="CARE_EN", version="1", locale="en",
                    category="precautions", urgency="routine", title="English",
                    content="Reviewed English guidance.", review_status="approved",
                    is_active=True, reviewed_by="clinical-reviewer",
                    reviewed_at=datetime.now(timezone.utc),
                    references=[RecommendationReference(reference=source)],
                ),
                CareRecommendation(
                    disease_id=disease.id, code="CARE_HI", version="1", locale="hi",
                    category="precautions", urgency="routine", title="Hindi",
                    content="Reviewed Hindi guidance.", review_status="approved",
                    is_active=True, reviewed_by="clinical-reviewer",
                    reviewed_at=datetime.now(timezone.utc),
                    references=[RecommendationReference(reference=source)],
                ),
            ]
        )
        db.commit()
        db.close()

        response = client.get(
            "/api/v1/knowledge/diseases/DIS_FILTER/recommendations",
            params={"locale": "hi", "category": "precautions"},
        )
        assert response.status_code == 200
        assert [item["code"] for item in response.json()["items"]] == ["CARE_HI"]
    finally:
        close_client(client)


def test_knowledge_api_does_not_expose_unknown_or_inactive_disease() -> None:
    client = make_client()
    try:
        response = client.get(
            "/api/v1/knowledge/diseases/NOT_FOUND/recommendations"
        )
        assert response.status_code == 404
    finally:
        close_client(client)

def test_knowledge_api_excludes_overdue_source_and_recommendation_reviews() -> None:
    client = make_client()
    try:
        db = TestingSessionLocal()
        disease = Disease(
            code="DIS_OVERDUE",
            name="Review condition",
            is_active=True,
            review_status="approved",
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(disease)
        db.flush()
        overdue_source = MedicalReference(
            title="Overdue source",
            publisher="Example authority",
            url="https://example.org/overdue-source",
            evidence_type="guideline",
            version="1",
            accessed_on=date.today(),
            review_status="approved",
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
            next_review_due=date.today() - timedelta(days=1),
        )
        current_source = MedicalReference(
            title="Current source",
            publisher="Example authority",
            url="https://example.org/current-source",
            evidence_type="guideline",
            version="1",
            accessed_on=date.today(),
            review_status="approved",
            reviewed_by="clinical-reviewer",
            reviewed_at=datetime.now(timezone.utc),
            next_review_due=date.today() + timedelta(days=30),
        )
        db.add_all([overdue_source, current_source])
        db.flush()
        db.add_all(
            [
                CareRecommendation(
                    disease_id=disease.id,
                    code="CARE_OVERDUE_SOURCE",
                    version="1",
                    locale="en",
                    category="general_care",
                    urgency="routine",
                    title="Overdue source guidance",
                    content="Must not be published.",
                    review_status="approved",
                    is_active=True,
                    reviewed_by="clinical-reviewer",
                    reviewed_at=datetime.now(timezone.utc),
                    references=[RecommendationReference(reference=overdue_source)],
                ),
                CareRecommendation(
                    disease_id=disease.id,
                    code="CARE_OVERDUE_REVIEW",
                    version="1",
                    locale="en",
                    category="general_care",
                    urgency="routine",
                    title="Overdue recommendation",
                    content="Must not be published either.",
                    review_status="approved",
                    is_active=True,
                    reviewed_by="clinical-reviewer",
                    reviewed_at=datetime.now(timezone.utc),
                    next_review_due=date.today() - timedelta(days=1),
                    references=[RecommendationReference(reference=current_source)],
                ),
            ]
        )
        db.commit()
        db.close()

        response = client.get(
            "/api/v1/knowledge/diseases/DIS_OVERDUE/recommendations"
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert "Must not be published" not in response.text
    finally:
        close_client(client)

