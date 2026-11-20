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
from app.core.security import create_access_token
from app.models.catalog import CatalogReviewEvent, Disease, DiseaseSymptom, Symptom
from app.models.user import RoleProvisioningEvent, User
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

def _user_headers(
    role: str,
    grant_scopes: bool = True,
    email_suffix: str = "reviewer",
) -> dict[str, str]:
    """Create a test account; reviewer fixtures receive explicit test scopes."""
    db = TestingSessionLocal()
    try:
        user = User(
            email=f"{role}-{email_suffix}@example.com",
            password_hash="test-only-not-used",
            role=role,
        )
        db.add(user)
        db.flush()
        if role == "reviewer" and grant_scopes:
            for scope_type in ("disease", "symptom", "disease_symptom"):
                db.add(
                    CatalogReviewerScope(
                        reviewer_id=user.id,
                        scope_type=scope_type,
                        scope_key=None,
                        granted_by=user.id,
                        grant_reason="Test fixture scope grant.",
                    )
                )
        db.commit()
        db.refresh(user)
        token = create_access_token(user.id)
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def test_patient_cannot_review_catalog_items(client: TestClient) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_REVIEW_DENIED", name="Review Denied"))
        db.commit()
    finally:
        db.close()

    headers = _user_headers("patient")
    response = client.patch(
        "/api/v1/catalog/review/diseases/DIS_REVIEW_DENIED",
        headers=headers,
        json={"expected_status": "draft",
            "status": "approved", "reason": "Reviewed against approved source."},
    )
    assert response.status_code == 403

    db = TestingSessionLocal()
    try:
        disease = db.query(Disease).filter_by(code="DIS_REVIEW_DENIED").one()
        assert disease.review_status == "draft"
        assert disease.reviewed_by is None
    finally:
        db.close()


def test_reviewer_can_approve_disease_with_server_assigned_audit(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_REVIEW_OK", name="Reviewable Condition"))
        db.commit()
    finally:
        db.close()

    headers = _user_headers("reviewer")
    response = client.patch(
        "/api/v1/catalog/review/diseases/DIS_REVIEW_OK",
        headers=headers,
        json={"expected_status": "draft",
            "status": "approved", "reason": "Clinical source and scope reviewed."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "approved"
    assert body["reviewed_by"]
    assert body["reviewed_at"]

    db = TestingSessionLocal()
    try:
        disease = db.query(Disease).filter_by(code="DIS_REVIEW_OK").one()
        assert disease.review_status == "approved"
        assert disease.reviewed_by == body["reviewed_by"]
        assert disease.reviewed_at is not None
    finally:
        db.close()


def test_registration_cannot_assign_reviewer_role(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "self-promote@example.com",
            "password": "StrongPass123!",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter_by(email="self-promote@example.com").one()
        assert user.role == "patient"
    finally:
        db.close()


def test_admin_can_review_disease_symptom_link(client: TestClient) -> None:
    db = TestingSessionLocal()
    try:
        disease = _approved_disease("DIS_LINK_REVIEW", "Linked Condition")
        symptom = _approved_symptom("SYM_LINK_REVIEW", "Linked Symptom")
        db.add_all([disease, symptom])
        db.flush()
        db.add(
            DiseaseSymptom(
                disease_id=disease.id,
                symptom_id=symptom.id,
                relevance_weight=1.0,
                review_status="draft",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.patch(
        "/api/v1/catalog/review/diseases/DIS_LINK_REVIEW/symptoms/SYM_LINK_REVIEW",
        headers=_user_headers("admin"),
        json={"expected_status": "draft",
            "status": "approved", "reason": "Relationship evidence reviewed."},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "approved"
    assert response.json()["reviewed_by"]

def test_review_decision_is_written_to_audit_history(client: TestClient) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_AUDIT_HISTORY", name="Audit History Condition"))
        db.commit()
    finally:
        db.close()

    headers = _user_headers("reviewer")
    response = client.patch(
        "/api/v1/catalog/review/diseases/DIS_AUDIT_HISTORY",
        headers=headers,
        json={
            "expected_status": "draft",
            "status": "approved",
            "reason": "Evidence and scope reviewed by assigned reviewer.",
        },
    )
    assert response.status_code == 200

    history = client.get(
        "/api/v1/catalog/review/history",
        headers=headers,
        params={"target_type": "disease", "target_key": "DIS_AUDIT_HISTORY"},
    )
    assert history.status_code == 200
    events = history.json()
    assert len(events) == 1
    assert events[0]["target_type"] == "disease"
    assert events[0]["target_key"] == "DIS_AUDIT_HISTORY"
    assert events[0]["previous_status"] == "draft"
    assert events[0]["new_status"] == "approved"
    assert events[0]["reason"] == "Evidence and scope reviewed by assigned reviewer."
    assert events[0]["reviewer_id"] == response.json()["reviewed_by"]
    assert events[0]["created_at"]


def test_patient_cannot_read_catalog_review_history(client: TestClient) -> None:
    response = client.get(
        "/api/v1/catalog/review/history",
        headers=_user_headers("patient"),
    )
    assert response.status_code == 403


def test_review_requires_a_reason(client: TestClient) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_NO_REASON", name="No Reason Condition"))
        db.commit()
    finally:
        db.close()

    response = client.patch(
        "/api/v1/catalog/review/diseases/DIS_NO_REASON",
        headers=_user_headers("reviewer"),
        json={"status": "approved"},
    )
    assert response.status_code == 422

def test_review_rejects_whitespace_only_reason(client: TestClient) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_BLANK_REASON", name="Blank Reason Condition"))
        db.commit()
    finally:
        db.close()

    response = client.patch(
        "/api/v1/catalog/review/diseases/DIS_BLANK_REASON",
        headers=_user_headers("reviewer"),
        json={"expected_status": "draft",
            "status": "approved", "reason": "         "},
    )
    assert response.status_code == 422

def test_reviewer_queue_lists_draft_catalog_items_and_relationships(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        disease = Disease(code="DIS_QUEUE", name="Queue Condition")
        symptom = Symptom(code="SYM_QUEUE", name="Queue Symptom")
        db.add_all([disease, symptom])
        db.flush()
        db.add(
            DiseaseSymptom(
                disease_id=disease.id,
                symptom_id=symptom.id,
                relevance_weight=1.0,
                review_status="draft",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/v1/catalog/review/queue",
        headers=_user_headers("reviewer"),
    )
    assert response.status_code == 200
    items = response.json()
    assert {
        (item["target_type"], item["target_key"], item["status"])
        for item in items
    } >= {
        ("disease", "DIS_QUEUE", "draft"),
        ("symptom", "SYM_QUEUE", "draft"),
        ("disease_symptom", "DIS_QUEUE:SYM_QUEUE", "draft"),
    }


def test_reviewer_queue_filters_status_and_rejects_patient(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_QUEUE_FILTER", name="Filtered Queue Condition"))
        db.commit()
    finally:
        db.close()

    patient = client.get(
        "/api/v1/catalog/review/queue",
        headers=_user_headers("patient"),
    )
    assert patient.status_code == 403

    filtered = client.get(
        "/api/v1/catalog/review/queue",
        headers=_user_headers("reviewer"),
        params={"status": "retired", "target_type": "disease"},
    )
    assert filtered.status_code == 200
    assert filtered.json() == []

def test_stale_catalog_review_decision_returns_conflict_without_audit_event(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_STALE_REVIEW", name="Stale Review Condition"))
        db.commit()
    finally:
        db.close()

    headers = _user_headers("reviewer")
    first = client.patch(
        "/api/v1/catalog/review/diseases/DIS_STALE_REVIEW",
        headers=headers,
        json={
            "expected_status": "draft",
            "status": "approved",
            "reason": "Evidence checked and approval recorded.",
        },
    )
    assert first.status_code == 200

    stale = client.patch(
        "/api/v1/catalog/review/diseases/DIS_STALE_REVIEW",
        headers=headers,
        json={
            "expected_status": "draft",
            "status": "retired",
            "reason": "Attempted stale decision after review.",
        },
    )
    assert stale.status_code == 409
    assert "changed after you opened it" in stale.json()["detail"]

    history = client.get(
        "/api/v1/catalog/review/history",
        headers=headers,
        params={"target_type": "disease", "target_key": "DIS_STALE_REVIEW"},
    )
    assert history.status_code == 200
    events = history.json()
    assert len(events) == 1
    assert events[0]["new_status"] == "approved"

@pytest.mark.parametrize(
    ("previous_status", "target_key"),
    [("unknown", "DIS_AUDIT_CONSTRAINT"), ("draft", "   ")],
)
def test_catalog_review_event_rejects_invalid_transition_metadata(
    client: TestClient,
    previous_status: str,
    target_key: str,
) -> None:
    headers = _user_headers("reviewer")
    db = TestingSessionLocal()
    try:
        reviewer = db.query(User).filter_by(email="reviewer-reviewer@example.com").one()
        db.add(
            CatalogReviewEvent(
                target_type="disease",
                target_key=target_key,
                previous_status=previous_status,
                new_status="approved",
                reason="Evidence and scope were reviewed.",
                reviewer_id=reviewer.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()

def test_admin_governance_overview_is_admin_only_and_reports_audited_state(
    client: TestClient,
) -> None:
    admin_headers = _user_headers("admin")
    patient_headers = _user_headers("patient")

    db = TestingSessionLocal()
    try:
        target = User(
            email="governance-target@example.com",
            password_hash="test-only-not-used",
            role="reviewer",
            email_verified=True,
        )
        disease = Disease(code="DIS_GOVERNANCE", name="Governance Test Condition")
        symptom = Symptom(code="SYM_GOVERNANCE", name="Governance Test Symptom")
        db.add_all([target, disease, symptom])
        db.flush()
        db.add(
            RoleProvisioningEvent(
                target_user_id=target.id,
                previous_role="patient",
                new_role="reviewer",
                operator_identity="operations@example.org",
                reason="Verified reviewer appointment and scope.",
            )
        )
        db.commit()
    finally:
        db.close()

    denied = client.get(
        "/api/v1/admin/governance",
        headers=patient_headers,
    )
    assert denied.status_code == 403

    reviewer_denied = client.get(
        "/api/v1/admin/governance",
        headers=_user_headers("reviewer"),
    )
    assert reviewer_denied.status_code == 403

    response = client.get(
        "/api/v1/admin/governance",
        headers=admin_headers,
        params={"history_limit": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accounts"]["reviewer"]["active"] == 2
    assert body["catalog"]["diseases"]["draft"] == 1
    assert body["catalog"]["symptoms"]["draft"] == 1
    assert len(body["recent_role_changes"]) == 1
    event = body["recent_role_changes"][0]
    assert event["previous_role"] == "patient"
    assert event["new_role"] == "reviewer"
    assert event["operator_identity"] == "operations@example.org"
    assert "password" not in event

def test_reviewer_without_assignment_cannot_read_queue_or_change_catalog(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_UNASSIGNED", name="Unassigned Condition"))
        db.commit()
    finally:
        db.close()

    headers = _user_headers("reviewer", grant_scopes=False)
    queue = client.get("/api/v1/catalog/review/queue", headers=headers)
    assert queue.status_code == 200
    assert queue.json() == []

    decision = client.patch(
        "/api/v1/catalog/review/diseases/DIS_UNASSIGNED",
        headers=headers,
        json={
            "expected_status": "draft",
            "status": "approved",
            "reason": "Reviewed evidence for this condition.",
        },
    )
    assert decision.status_code == 403


def test_admin_can_grant_exact_reviewer_scope_and_revoke_with_audit(
    client: TestClient,
) -> None:
    admin_headers = _user_headers("admin")
    reviewer_headers = _user_headers("reviewer", grant_scopes=False)

    db = TestingSessionLocal()
    try:
        reviewer = db.query(User).filter_by(email="reviewer-reviewer@example.com").one()
        reviewer.email_verified = True
        db.add_all([
            Disease(code="DIS_SCOPE_ALLOWED", name="Allowed Condition"),
            Disease(code="DIS_SCOPE_DENIED", name="Denied Condition"),
        ])
        db.commit()
        reviewer_id = str(reviewer.id)
    finally:
        db.close()

    granted = client.post(
        "/api/v1/admin/reviewer-scopes",
        headers=admin_headers,
        json={
            "reviewer_id": reviewer_id,
            "scope_type": "disease",
            "scope_key": "DIS_SCOPE_ALLOWED",
            "reason": "Assigned this disease review responsibility.",
        },
    )
    assert granted.status_code == 201
    scope_id = granted.json()["id"]
    assert granted.json()["reviewer_email"] == "reviewer-reviewer@example.com"

    allowed = client.patch(
        "/api/v1/catalog/review/diseases/DIS_SCOPE_ALLOWED",
        headers=reviewer_headers,
        json={
            "expected_status": "draft",
            "status": "in_review",
            "reason": "Initial evidence review has started.",
        },
    )
    assert allowed.status_code == 200

    denied = client.patch(
        "/api/v1/catalog/review/diseases/DIS_SCOPE_DENIED",
        headers=reviewer_headers,
        json={
            "expected_status": "draft",
            "status": "in_review",
            "reason": "Attempt to review an unassigned item.",
        },
    )
    assert denied.status_code == 403

    revoked = client.post(
        f"/api/v1/admin/reviewer-scopes/{scope_id}/revoke",
        headers=admin_headers,
        json={"reason": "Review assignment period has ended."},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"]

    after_revoke = client.patch(
        "/api/v1/catalog/review/diseases/DIS_SCOPE_ALLOWED",
        headers=reviewer_headers,
        json={
            "expected_status": "in_review",
            "status": "approved",
            "reason": "Attempt after the scope was revoked.",
        },
    )
    assert after_revoke.status_code == 403

    history = client.get(
        "/api/v1/admin/reviewer-scopes/history",
        headers=admin_headers,
    )
    assert history.status_code == 200
    assert {event["event_type"] for event in history.json()} == {"granted", "revoked"}


def test_only_admin_can_manage_reviewer_scopes_and_verified_reviewers_are_required(
    client: TestClient,
) -> None:
    reviewer_headers = _user_headers("reviewer")
    patient_headers = _user_headers("patient")
    admin_headers = _user_headers("admin")

    forbidden = client.get("/api/v1/admin/reviewer-scopes", headers=reviewer_headers)
    assert forbidden.status_code == 403
    forbidden_patient = client.get("/api/v1/admin/reviewer-scopes", headers=patient_headers)
    assert forbidden_patient.status_code == 403

    db = TestingSessionLocal()
    try:
        target = User(
            email="unverified-reviewer@example.com",
            password_hash="test-only-not-used",
            role="reviewer",
            email_verified=False,
        )
        db.add(target)
        db.commit()
        target_id = str(target.id)
    finally:
        db.close()

    response = client.post(
        "/api/v1/admin/reviewer-scopes",
        headers=admin_headers,
        json={
            "reviewer_id": target_id,
            "scope_type": "disease",
            "scope_key": None,
            "reason": "Assign all disease catalog review work.",
        },
    )
    assert response.status_code == 404

def test_reviewer_history_is_limited_to_own_decisions(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(Disease(code="DIS_PRIVATE_REVIEW_HISTORY", name="Private Review History"))
        db.commit()
    finally:
        db.close()

    first_reviewer = _user_headers("reviewer")
    second_reviewer = _user_headers("reviewer", email_suffix="second")
    decision = client.patch(
        "/api/v1/catalog/review/diseases/DIS_PRIVATE_REVIEW_HISTORY",
        headers=first_reviewer,
        json={
            "expected_status": "draft",
            "status": "in_review",
            "reason": "Initial review assigned and started.",
        },
    )
    assert decision.status_code == 200

    own_history = client.get(
        "/api/v1/catalog/review/history",
        headers=first_reviewer,
        params={"target_key": "DIS_PRIVATE_REVIEW_HISTORY"},
    )
    other_history = client.get(
        "/api/v1/catalog/review/history",
        headers=second_reviewer,
        params={"target_key": "DIS_PRIVATE_REVIEW_HISTORY"},
    )
    assert own_history.status_code == 200
    assert len(own_history.json()) == 1
    assert other_history.status_code == 200
    assert other_history.json() == []

def test_reviewer_workload_counts_only_assigned_items_and_personal_activity(
    client: TestClient,
) -> None:
    headers = _user_headers("reviewer", grant_scopes=False)
    db = TestingSessionLocal()
    try:
        reviewer = db.query(User).filter_by(email="reviewer-reviewer@example.com").one()
        db.add_all([
            Disease(code="DIS_WORKLOAD_ASSIGNED", name="Assigned Workload Condition"),
            Disease(code="DIS_WORKLOAD_OTHER", name="Other Workload Condition"),
            Symptom(code="SYM_WORKLOAD_OTHER", name="Other Workload Symptom"),
        ])
        db.flush()
        db.add(
            CatalogReviewerScope(
                reviewer_id=reviewer.id,
                scope_type="disease",
                scope_key="DIS_WORKLOAD_ASSIGNED",
                granted_by=reviewer.id,
                grant_reason="Test exact workload assignment.",
            )
        )
        db.commit()
    finally:
        db.close()

    initial = client.get("/api/v1/catalog/review/workload", headers=headers)
    assert initial.status_code == 200
    initial_body = initial.json()
    assert initial_body["pending_total"] == 1
    assert initial_body["pending_by_type"] == {
        "disease": 1,
        "symptom": 0,
        "disease_symptom": 0,
    }
    assert initial_body["is_unrestricted"] is False
    assert len(initial_body["assignments"]) == 1
    assert initial_body["assignments"][0]["scope_type"] == "disease"
    assert initial_body["assignments"][0]["scope_key"] == "DIS_WORKLOAD_ASSIGNED"
    assert initial_body["assignments"][0]["granted_at"]
    assert initial_body["activity"] == {
        "total_decisions": 0,
        "approved_decisions": 0,
        "retired_decisions": 0,
        "decisions_last_7_days": 0,
    }

    decision = client.patch(
        "/api/v1/catalog/review/diseases/DIS_WORKLOAD_ASSIGNED",
        headers=headers,
        json={
            "expected_status": "draft",
            "status": "approved",
            "reason": "Reviewed source evidence and catalog scope.",
        },
    )
    assert decision.status_code == 200

    updated = client.get("/api/v1/catalog/review/workload", headers=headers)
    assert updated.status_code == 200
    assert updated.json()["pending_total"] == 0
    assert updated.json()["activity"]["total_decisions"] == 1
    assert updated.json()["activity"]["approved_decisions"] == 1

    other_reviewer = _user_headers("reviewer", email_suffix="workload-other", grant_scopes=False)
    isolated = client.get(
        "/api/v1/catalog/review/workload",
        headers=other_reviewer,
    )
    assert isolated.status_code == 200
    assert isolated.json()["activity"]["total_decisions"] == 0
    assert isolated.json()["assignments"] == []


def test_reviewer_workload_requires_catalog_reviewer_role(
    client: TestClient,
) -> None:
    patient_headers = _user_headers("patient")
    response = client.get("/api/v1/catalog/review/workload", headers=patient_headers)
    assert response.status_code == 403

def test_review_history_filters_and_entry_detail_are_authorized(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all([
            Disease(
                code="DIS_HISTORY_DETAIL",
                name="History Detail Condition",
                description="A test catalog description.",
            ),
            Symptom(
                code="SYM_HISTORY_DETAIL",
                name="History Detail Symptom",
                description="A test symptom description.",
            ),
        ])
        db.commit()
    finally:
        db.close()

    reviewer_headers = _user_headers("reviewer")
    disease_decision = client.patch(
        "/api/v1/catalog/review/diseases/DIS_HISTORY_DETAIL",
        headers=reviewer_headers,
        json={
            "expected_status": "draft",
            "status": "approved",
            "reason": "Evidence checked for condition approval.",
        },
    )
    symptom_decision = client.patch(
        "/api/v1/catalog/review/symptoms/SYM_HISTORY_DETAIL",
        headers=reviewer_headers,
        json={
            "expected_status": "draft",
            "status": "in_review",
            "reason": "Need another source before approval.",
        },
    )
    assert disease_decision.status_code == 200
    assert symptom_decision.status_code == 200

    db = TestingSessionLocal()
    try:
        disease_event = db.query(CatalogReviewEvent).filter_by(
            target_key="DIS_HISTORY_DETAIL"
        ).one()
        disease_event_id = str(disease_event.id)
    finally:
        db.close()

    filtered = client.get(
        "/api/v1/catalog/review/history",
        headers=reviewer_headers,
        params={
            "target_type": "disease",
            "q": "condition approval",
            "date_from": "2020-01-01",
            "date_to": "2099-12-31",
        },
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["target_key"] == "DIS_HISTORY_DETAIL"

    invalid_dates = client.get(
        "/api/v1/catalog/review/history",
        headers=reviewer_headers,
        params={"date_from": "2099-01-01", "date_to": "2020-01-01"},
    )
    assert invalid_dates.status_code == 422

    detail = client.get(
        f"/api/v1/catalog/review/history/{disease_event_id}/entry",
        headers=reviewer_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["entry"]["name"] == "History Detail Condition"
    assert detail.json()["entry"]["status"] == "approved"
    assert detail.json()["event"]["target_key"] == "DIS_HISTORY_DETAIL"

    other_reviewer = _user_headers(
        "reviewer", email_suffix="history-entry-other"
    )
    forbidden_detail = client.get(
        f"/api/v1/catalog/review/history/{disease_event_id}/entry",
        headers=other_reviewer,
    )
    assert forbidden_detail.status_code == 404

def test_reviewer_queue_search_and_offset_pagination_are_stable(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all([
            Disease(code="DIS_PAGE_A", name="Pagination Alpha"),
            Disease(code="DIS_PAGE_B", name="Pagination Beta"),
            Disease(code="DIS_PAGE_C", name="Pagination Gamma"),
            Disease(code="DIS_PAGE_D", name="Unrelated Condition"),
        ])
        db.commit()
    finally:
        db.close()

    headers = _user_headers("reviewer")
    first = client.get(
        "/api/v1/catalog/review/queue",
        headers=headers,
        params={"target_type": "disease", "q": "Pagination", "limit": 2},
    )
    assert first.status_code == 200
    first_items = first.json()
    assert [item["target_key"] for item in first_items] == [
        "DIS_PAGE_A", "DIS_PAGE_B", "DIS_PAGE_C"
    ]

    second = client.get(
        "/api/v1/catalog/review/queue",
        headers=headers,
        params={
            "target_type": "disease", "q": "Pagination",
            "limit": 2, "offset": 2,
        },
    )
    assert second.status_code == 200
    assert [item["target_key"] for item in second.json()] == ["DIS_PAGE_C"]

    empty = client.get(
        "/api/v1/catalog/review/queue",
        headers=headers,
        params={
            "target_type": "disease", "q": "Pagination",
            "limit": 2, "offset": 4,
        },
    )
    assert empty.status_code == 200
    assert empty.json() == []

    no_match = client.get(
        "/api/v1/catalog/review/queue",
        headers=headers,
        params={"target_type": "disease", "q": "No such catalog entry"},
    )
    assert no_match.status_code == 200
    assert no_match.json() == []



def test_pending_entry_inspection_returns_relationship_context_and_no_fake_evidence(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        disease = Disease(code="DIS_INSPECT", name="Inspection Condition",
                          description="Condition description.", review_status="in_review")
        symptom = Symptom(code="SYM_INSPECT", name="Inspection Symptom",
                          description="Symptom description.", review_status="draft")
        db.add_all([disease, symptom])
        db.flush()
        db.add(DiseaseSymptom(
            disease_id=disease.id,
            symptom_id=symptom.id,
            relevance_weight=0.75,
            review_status="in_review",
        ))
        db.commit()
    finally:
        db.close()

    headers = _user_headers("reviewer")
    disease_detail = client.get(
        "/api/v1/catalog/review/queue/entry",
        headers=headers,
        params={"target_type": "disease", "target_key": "DIS_INSPECT"},
    )
    assert disease_detail.status_code == 200
    body = disease_detail.json()
    assert body["entry"]["name"] == "Inspection Condition"
    assert body["entry"]["status"] == "in_review"
    assert body["entry"]["description"] == "Condition description."
    assert body["evidence"]["references"] == []
    assert body["evidence"]["reference_support"] == "not_implemented"
    assert "No source-reference records" in body["evidence"]["message"]

    link_detail = client.get(
        "/api/v1/catalog/review/queue/entry",
        headers=headers,
        params={"target_type": "disease_symptom", "target_key": "DIS_INSPECT:SYM_INSPECT"},
    )
    assert link_detail.status_code == 200
    link = link_detail.json()["entry"]
    assert link["relevance_weight"] == 0.75
    assert {item["target_type"] for item in link["related_entries"]} == {
        "disease", "symptom"
    }


def test_pending_entry_inspection_enforces_role_scope_and_pending_state(
    client: TestClient,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add_all([
            Disease(code="DIS_INSPECT_ALLOWED", name="Allowed Inspection"),
            Disease(code="DIS_INSPECT_DENIED", name="Denied Inspection"),
            _approved_disease("DIS_INSPECT_APPROVED", "Already Approved"),
        ])
        db.commit()
    finally:
        db.close()

    patient = client.get(
        "/api/v1/catalog/review/queue/entry",
        headers=_user_headers("patient"),
        params={"target_type": "disease", "target_key": "DIS_INSPECT_ALLOWED"},
    )
    assert patient.status_code == 403

    unassigned_headers = _user_headers(
        "reviewer", grant_scopes=False, email_suffix="inspect-unassigned"
    )
    # The fixture's reviewer identity is shared by role; remove its grants by
    # using a distinct reviewer identity with no active scope.
    db = TestingSessionLocal()
    try:
        reviewer = db.query(User).filter_by(
            email="reviewer-inspect-unassigned@example.com"
        ).one()
        db.query(CatalogReviewerScope).filter_by(reviewer_id=reviewer.id).delete()
        db.commit()
    finally:
        db.close()

    denied = client.get(
        "/api/v1/catalog/review/queue/entry",
        headers=unassigned_headers,
        params={"target_type": "disease", "target_key": "DIS_INSPECT_ALLOWED"},
    )
    assert denied.status_code == 403

    assigned = client.get(
        "/api/v1/catalog/review/queue/entry",
        headers=_user_headers("reviewer"),
        params={"target_type": "disease", "target_key": "DIS_INSPECT_ALLOWED"},
    )
    assert assigned.status_code == 200

    approved = client.get(
        "/api/v1/catalog/review/queue/entry",
        headers=_user_headers("reviewer"),
        params={"target_type": "disease", "target_key": "DIS_INSPECT_APPROVED"},
    )
    assert approved.status_code == 404

    missing = client.get(
        "/api/v1/catalog/review/queue/entry",
        headers=_user_headers("admin"),
        params={"target_type": "disease", "target_key": "DOES_NOT_EXIST"},
    )
    assert missing.status_code == 404
