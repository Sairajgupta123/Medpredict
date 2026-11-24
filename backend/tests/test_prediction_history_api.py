"""Authenticated API tests for prediction-history privacy controls."""

from datetime import datetime, timezone
from uuid import UUID

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
    SkinImageReviewEvent,
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
        db.flush()
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

def test_history_paginates_with_total_limit_and_offset(client: TestClient) -> None:
    token, user = _register(client, "history-pagination@example.com")
    first = _prediction(user.id, input_text="private first narrative")
    second = _prediction(user.id, input_text="private second narrative")
    third = _prediction(user.id, input_text="private third narrative")

    response = client.get(
        "/api/v1/predictions/history?limit=2&offset=1",
        headers=_headers(token),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert len(payload["items"]) == 2
    assert {entry["id"] for entry in payload["items"]} <= {
        str(first.id), str(second.id), str(third.id)
    }
    assert all("input_text" not in entry for entry in payload["items"])
    assert "private " not in response.text


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
            select(PredictionConsentEvent)
            .where(PredictionConsentEvent.prediction_id == item.id)
            .order_by(PredictionConsentEvent.captured_at.desc())
            .limit(1)
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


class _FakeIntakeStorage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_private(self, object_key: str, content: bytes, content_type: str) -> None:
        if self.fail:
            raise OSError("simulated private storage outage")
        self.objects[object_key] = (content, content_type)

    def get_private(self, object_key: str) -> bytes:
        return self.objects[object_key][0]

    def delete_private(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


def _small_png() -> bytes:
    from io import BytesIO
    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (320, 320), (120, 80, 60)).save(output, format="PNG")
    return output.getvalue()


def _intake_form() -> dict[str, str]:
    return {
        "processing_consent": "true",
        "history_consent": "true",
        "review_consent": "true",
        "processing_policy_version": "image-processing-v1",
        "history_policy_version": "image-history-v1",
        "review_policy_version": "image-review-v1",
    }


def test_skin_image_intake_requires_all_separate_consents(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = _register(client, "image-consent-required@example.com")
    response = client.post(
        "/api/v1/skin-images/intake",
        headers=_headers(token),
        data={**_intake_form(), "history_consent": "false"},
        files={"image": ("skin.png", _small_png(), "image/png")},
    )
    assert response.status_code == 422
    assert "separate" in response.json()["detail"].lower()


def test_skin_image_intake_stores_sanitized_image_after_explicit_consents(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images

    token, user = _register(client, "image-intake@example.com")
    storage = _FakeIntakeStorage()
    monkeypatch.setattr(skin_images, "build_skin_image_storage", lambda: storage)

    response = client.post(
        "/api/v1/skin-images/intake",
        headers=_headers(token),
        data=_intake_form(),
        files={"image": ("skin.png", _small_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["storage_status"] == "stored"
    assert body["clinical_interpretation_performed"] is False
    assert body["disease_prediction_performed"] is False
    assert "object_key" not in body and "url" not in body
    assert len(storage.objects) == 1

    db = TestingSessionLocal()
    try:
        prediction = db.get(Prediction, UUID(body["prediction_id"]))
        assert prediction is not None
        assert prediction.user_id == user.id
        assert prediction.status == "review_required"
        image = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        assert image is not None and image.storage_status == "stored"
        events = list(
            db.scalars(
                select(PredictionConsentEvent).where(
                    PredictionConsentEvent.prediction_id == prediction.id
                )
            ).all()
        )
        assert {event.purpose for event in events} == {
            "skin_image_processing",
            "skin_image_history",
            "skin_image_review",
        }
        review_event = next(event for event in events if event.purpose == "skin_image_review")
        assert review_event.policy_version == "image-review-v1"
    finally:
        db.close()


def test_skin_image_intake_records_failed_storage_without_claiming_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images

    token, user = _register(client, "image-intake-failure@example.com")
    monkeypatch.setattr(
        skin_images,
        "build_skin_image_storage",
        lambda: _FakeIntakeStorage(fail=True),
    )
    response = client.post(
        "/api/v1/skin-images/intake",
        headers=_headers(token),
        data=_intake_form(),
        files={"image": ("skin.png", _small_png(), "image/png")},
    )
    assert response.status_code == 503
    db = TestingSessionLocal()
    try:
        prediction = db.scalar(
            select(Prediction).where(Prediction.user_id == user.id)
        )
        assert prediction is not None
        image = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        assert image is not None and image.storage_status == "failed"
        failed_prediction_id = prediction.id
    finally:
        db.close()

    # A failed write must never be presented as a stored image or reach object storage.
    status_response = client.get(
        f"/api/v1/skin-images/{failed_prediction_id}/review-status",
        headers=_headers(token),
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == "submission_unavailable"
    assert status_payload["clinical_interpretation_performed"] is False
    assert status_payload["disease_prediction_performed"] is False

    image_response = client.get(
        f"/api/v1/skin-images/{failed_prediction_id}",
        headers=_headers(token),
    )
    assert image_response.status_code == 404


def test_skin_image_intake_fails_closed_when_storage_is_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images
    from app.services.skin_image_storage import DisabledSkinImageStorage

    token, _ = _register(client, "image-intake-disabled@example.com")
    monkeypatch.setattr(
        skin_images, "build_skin_image_storage", DisabledSkinImageStorage
    )
    response = client.post(
        "/api/v1/skin-images/intake",
        headers=_headers(token),
        data=_intake_form(),
        files={"image": ("skin.png", _small_png(), "image/png")},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def _stored_image_for_user(user_id, *, grant_history: bool = True):
    import hashlib

    from app.services.skin_image_validation import validate_and_sanitize_skin_image

    item = _prediction(user_id, modality="skin_image")
    sanitized = validate_and_sanitize_skin_image(_small_png(), "image/png")
    key = "skin-images/11111111111111111111111111111111.png"
    db = TestingSessionLocal()
    try:
        record = SkinImageAnalysis(
            prediction_id=item.id,
            object_key=key,
            content_type=sanitized.content_type,
            image_sha256=hashlib.sha256(sanitized.content).hexdigest(),
            storage_status="stored",
        )
        db.add(record)
        if grant_history:
            db.add(
                PredictionConsentEvent(
                    prediction_id=item.id,
                    purpose="skin_image_history",
                    action="granted",
                    policy_version="image-history-v1",
                )
            )
        db.commit()
    finally:
        db.close()
    return item, key, sanitized.content


def test_owner_can_retrieve_image_with_active_history_consent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images

    token, user = _register(client, "image-read-owner@example.com")
    item, key, content = _stored_image_for_user(user.id)
    storage = _FakeIntakeStorage()
    storage.objects[key] = (content, "image/png")
    monkeypatch.setattr(skin_images, "build_skin_image_storage", lambda: storage)

    response = client.get(
        f"/api/v1/skin-images/{item.id}", headers=_headers(token)
    )
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "object_key" not in response.headers


def test_other_user_cannot_retrieve_skin_image(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images

    token, _ = _register(client, "image-read-stranger@example.com")
    _, owner = _register(client, "image-read-actual-owner@example.com")
    item, _, _ = _stored_image_for_user(owner.id)
    storage = _FakeIntakeStorage()
    monkeypatch.setattr(skin_images, "build_skin_image_storage", lambda: storage)

    response = client.get(
        f"/api/v1/skin-images/{item.id}", headers=_headers(token)
    )
    assert response.status_code == 404
    assert storage.objects == {}


def test_image_retrieval_requires_active_history_consent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images

    token, user = _register(client, "image-read-no-consent@example.com")
    item, _, _ = _stored_image_for_user(user.id, grant_history=False)
    monkeypatch.setattr(
        skin_images, "build_skin_image_storage", lambda: _FakeIntakeStorage()
    )

    response = client.get(
        f"/api/v1/skin-images/{item.id}", headers=_headers(token)
    )
    assert response.status_code == 403


def test_image_retrieval_rejects_corrupted_private_object(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images

    token, user = _register(client, "image-read-corrupt@example.com")
    item, key, content = _stored_image_for_user(user.id)
    storage = _FakeIntakeStorage()
    storage.objects[key] = (content + b"tampered", "image/png")
    monkeypatch.setattr(skin_images, "build_skin_image_storage", lambda: storage)

    response = client.get(
        f"/api/v1/skin-images/{item.id}", headers=_headers(token)
    )
    assert response.status_code == 503
    assert "integrity" in response.json()["detail"].lower()


def test_skin_image_retrieval_revalidates_jpeg_without_changing_stored_bytes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    from io import BytesIO
    from PIL import Image
    from app.api.v1 import skin_images

    token, user = _register(client, "image-read-jpeg@example.com")
    output = BytesIO()
    Image.new("RGB", (320, 320), (120, 80, 60)).save(
        output, format="JPEG", quality=88
    )
    jpeg_bytes = output.getvalue()
    item = _prediction(user.id, modality="skin_image")
    key = "skin-images/22222222222222222222222222222222.jpg"
    db = TestingSessionLocal()
    try:
        db.add(
            SkinImageAnalysis(
                prediction_id=item.id,
                object_key=key,
                content_type="image/jpeg",
                image_sha256=hashlib.sha256(jpeg_bytes).hexdigest(),
                storage_status="stored",
            )
        )
        db.add(
            PredictionConsentEvent(
                prediction_id=item.id,
                purpose="skin_image_history",
                action="granted",
                policy_version="image-history-v1",
            )
        )
        db.commit()
    finally:
        db.close()

    storage = _FakeIntakeStorage()
    storage.objects[key] = (jpeg_bytes, "image/jpeg")
    monkeypatch.setattr(skin_images, "build_skin_image_storage", lambda: storage)
    response = client.get(
        f"/api/v1/skin-images/{item.id}", headers=_headers(token)
    )
    assert response.status_code == 200
    assert response.content == jpeg_bytes


def test_skin_image_retrieval_requires_authentication(client: TestClient) -> None:
    response = client.get(
        "/api/v1/skin-images/00000000-0000-0000-0000-000000000001"
    )
    assert response.status_code == 401


def test_image_retrieval_fails_closed_when_storage_initialization_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images

    token, user = _register(client, "image-read-storage-init@example.com")
    item, _, _ = _stored_image_for_user(user.id)

    def unavailable_storage():
        raise OSError("simulated SDK configuration failure")

    monkeypatch.setattr(
        skin_images, "build_skin_image_storage", unavailable_storage
    )
    response = client.get(
        f"/api/v1/skin-images/{item.id}", headers=_headers(token)
    )
    assert response.status_code == 503
    assert "storage is unavailable" in response.json()["detail"].lower()


def _prepare_skin_review_item(owner_id):
    import hashlib

    from app.services.skin_image_validation import validate_and_sanitize_skin_image

    prediction = _prediction(owner_id, modality="skin_image")
    sanitized = validate_and_sanitize_skin_image(_small_png(), "image/png")
    key = "skin-images/33333333333333333333333333333333.png"
    db = TestingSessionLocal()
    try:
        image = SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key=key,
            content_type="image/png",
            image_sha256=hashlib.sha256(sanitized.content).hexdigest(),
            storage_status="stored",
        )
        db.add(image)
        db.add_all([
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_processing",
                action="granted",
                policy_version="image-processing-v1",
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_review",
                action="granted",
                policy_version="image-review-v1",
            ),
        ])
        db.commit()
    finally:
        db.close()
    return prediction, key, sanitized.content




def _grant_skin_image_review_scope(reviewer_id, prediction_id, granted_by):
    from app.models.reviewer_scope import CatalogReviewerScope

    db = TestingSessionLocal()
    try:
        db.add(
            CatalogReviewerScope(
                reviewer_id=reviewer_id,
                scope_type="skin_image",
                scope_key=str(prediction_id),
                granted_by=granted_by,
                grant_reason="Authorized for this specific skin image.",
            )
        )
        db.commit()
    finally:
        db.close()


def _set_account_role(user_id, role):
    db = TestingSessionLocal()
    try:
        user = db.get(User, user_id)
        user.role = role
        user.email_verified = True
        db.commit()
    finally:
        db.close()


def test_admin_assigns_image_to_verified_reviewer_and_review_is_audited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images
    from app.models.prediction import SkinImageReviewEvent

    admin_token, admin = _register(client, "skin-review-admin@example.com")
    reviewer_token, reviewer = _register(client, "skin-reviewer@example.com")
    owner_token, owner = _register(client, "skin-review-owner@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")
    prediction, key, image_bytes = _prepare_skin_review_item(owner.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)
    storage = _FakeIntakeStorage()
    storage.objects[key] = (image_bytes, "image/png")
    monkeypatch.setattr(skin_images, "build_skin_image_storage", lambda: storage)

    assigned = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={"reviewer_id": str(reviewer.id), "reason": "Assigned for image quality review."},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["review_status"] == "assigned"

    queue = client.get("/api/v1/skin-images/review/queue", headers=_headers(reviewer_token))
    assert queue.status_code == 200
    assert [row["prediction_id"] for row in queue.json()] == [str(prediction.id)]

    image_response = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/image",
        headers=_headers(reviewer_token),
    )
    assert image_response.status_code == 200
    assert image_response.content == image_bytes
    assert image_response.headers["cache-control"].startswith("private, no-store")

    decision = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/decision",
        headers=_headers(reviewer_token),
        json={
            "outcome": "capture_adequate",
            "reason": "Image framing and exposure are adequate.",
        },
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["review_status"] == "reviewed"
    assert decision.json()["clinical_interpretation_performed"] is False
    assert client.get(
        "/api/v1/skin-images/review/queue", headers=_headers(reviewer_token)
    ).json() == []

    db = TestingSessionLocal()
    try:
        events = db.scalars(
            select(SkinImageReviewEvent).where(
                SkinImageReviewEvent.prediction_id == prediction.id
            )
        ).all()
        assert [event.event_type for event in events] == [
            "assigned",
            "image_accessed",
            "reviewed",
        ]
        assert events[0].actor_id == admin.id
        assert events[1].actor_id == reviewer.id
        assert events[2].actor_id == reviewer.id
        assert events[1].reason == "Authorized private image retrieval completed."
        reviewed_image = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        assert reviewed_image is not None and reviewed_image.review_required is True
    finally:
        db.close()


def test_image_review_is_not_available_to_patient_or_unassigned_reviewer(
    client: TestClient,
) -> None:
    patient_token, patient = _register(client, "skin-review-patient@example.com")
    reviewer_token, reviewer = _register(client, "skin-review-unassigned@example.com")
    _set_account_role(reviewer.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(patient.id)

    patient_queue = client.get(
        "/api/v1/skin-images/review/queue", headers=_headers(patient_token)
    )
    assert patient_queue.status_code == 403

    unassigned_image = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/image",
        headers=_headers(reviewer_token),
    )
    assert unassigned_image.status_code == 404


def test_image_review_assignment_rejects_unverified_reviewer(
    client: TestClient,
) -> None:
    admin_token, admin = _register(client, "skin-review-admin-unverified@example.com")
    reviewer_token, reviewer = _register(client, "skin-review-unverified@example.com")
    _set_account_role(admin.id, "admin")
    prediction, _, _ = _prepare_skin_review_item(admin.id)
    db = TestingSessionLocal()
    try:
        account = db.get(User, reviewer.id)
        account.role = "reviewer"
        account.email_verified = False
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={"reviewer_id": str(reviewer.id), "reason": "Assignment for review."},
    )
    assert response.status_code == 404


def test_image_review_audit_is_visible_only_to_assignee_or_admin(
    client: TestClient,
) -> None:
    from app.models.prediction import SkinImageReviewEvent

    reviewer_token, reviewer = _register(client, "skin-audit-reviewer@example.com")
    other_token, other = _register(client, "skin-audit-other@example.com")
    _set_account_role(reviewer.id, "reviewer")
    _set_account_role(other.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(reviewer.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, other.id)
    db = TestingSessionLocal()
    try:
        image = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        image.review_status = "assigned"
        image.assigned_reviewer_id = reviewer.id
        db.add(
            SkinImageReviewEvent(
                prediction_id=prediction.id,
                image_analysis_id=image.id,
                event_type="assigned",
                actor_id=other.id,
                assigned_reviewer_id=reviewer.id,
                reason="Assigned for technical image review.",
            )
        )
        db.commit()
    finally:
        db.close()

    own = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/events",
        headers=_headers(reviewer_token),
    )
    assert own.status_code == 200
    assert len(own.json()) == 1

    forbidden = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/events",
        headers=_headers(other_token),
    )
    assert forbidden.status_code == 404


def test_admin_review_queue_includes_unassigned_stored_images(
    client: TestClient,
) -> None:
    admin_token, admin = _register(client, "skin-review-pending-admin@example.com")
    _set_account_role(admin.id, "admin")
    prediction, _, _ = _prepare_skin_review_item(admin.id)

    response = client.get(
        "/api/v1/skin-images/review/queue", headers=_headers(admin_token)
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["prediction_id"] == str(prediction.id)
    assert response.json()[0]["review_status"] == "pending"


def test_admin_cannot_assign_skin_image_without_explicit_image_scope(
    client: TestClient,
) -> None:
    admin_token, admin = _register(client, "skin-review-no-scope-admin@example.com")
    reviewer_token, reviewer = _register(client, "skin-review-no-scope@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(admin.id)
    from app.models.reviewer_scope import CatalogReviewerScope

    db = TestingSessionLocal()
    try:
        db.add(
            CatalogReviewerScope(
                reviewer_id=reviewer.id,
                scope_type="disease",
                scope_key="CATALOG_ONLY",
                granted_by=admin.id,
                grant_reason="Catalog review access only.",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={"reviewer_id": str(reviewer.id), "reason": "Assign image for review."},
    )
    assert response.status_code == 403
    assert "skin-image review scope" in response.json()["detail"]


def test_revoked_skin_image_scope_blocks_assigned_reviewer_access(
    client: TestClient,
) -> None:
    from datetime import datetime, timezone

    from app.models.reviewer_scope import CatalogReviewerScope

    reviewer_token, reviewer = _register(client, "skin-review-revoked@example.com")
    admin_token, admin = _register(client, "skin-review-revoked-admin@example.com")
    _set_account_role(reviewer.id, "reviewer")
    _set_account_role(admin.id, "admin")
    prediction, _, _ = _prepare_skin_review_item(reviewer.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)
    db = TestingSessionLocal()
    try:
        image = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        image.review_status = "assigned"
        image.assigned_reviewer_id = reviewer.id
        scope = db.scalar(
            select(CatalogReviewerScope).where(
                CatalogReviewerScope.reviewer_id == reviewer.id,
                CatalogReviewerScope.scope_type == "skin_image",
                CatalogReviewerScope.scope_key == str(prediction.id),
            )
        )
        scope.revoked_by = admin.id
        scope.revoked_at = datetime.now(timezone.utc)
        scope.revoke_reason = "Reviewer access is no longer authorized."
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/image",
        headers=_headers(reviewer_token),
    )
    assert response.status_code == 403


def test_admin_can_grant_a_prediction_specific_skin_image_scope(
    client: TestClient,
) -> None:
    admin_token, admin = _register(client, "skin-scope-admin@example.com")
    reviewer_token, reviewer = _register(client, "skin-scope-reviewer@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(admin.id)

    grant = client.post(
        "/api/v1/admin/reviewer-scopes",
        headers=_headers(admin_token),
        json={
            "reviewer_id": str(reviewer.id),
            "scope_type": "skin_image",
            "scope_key": str(prediction.id),
            "reason": "Authorized for one image review.",
        },
    )
    assert grant.status_code == 201, grant.text
    assert grant.json()["scope_type"] == "skin_image"
    assert grant.json()["scope_key"] == str(prediction.id)

    scopes = client.get(
        "/api/v1/admin/reviewer-scopes?include_revoked=false",
        headers=_headers(admin_token),
    )
    assert scopes.status_code == 200
    assert any(
        row["reviewer_id"] == str(reviewer.id)
        and row["scope_type"] == "skin_image"
        and row["scope_key"] == str(prediction.id)
        for row in scopes.json()
    )

    forbidden = client.post(
        "/api/v1/admin/reviewer-scopes",
        headers=_headers(reviewer_token),
        json={
            "reviewer_id": str(reviewer.id),
            "scope_type": "skin_image",
            "scope_key": str(prediction.id),
            "reason": "Reviewer cannot grant self scope.",
        },
    )
    assert forbidden.status_code == 403


def test_skin_image_scope_rejects_broad_null_scope(
    client: TestClient,
) -> None:
    admin_token, admin = _register(client, "skin-scope-null-admin@example.com")
    reviewer_token, reviewer = _register(client, "skin-scope-null-reviewer@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")

    response = client.post(
        "/api/v1/admin/reviewer-scopes",
        headers=_headers(admin_token),
        json={
            "reviewer_id": str(reviewer.id),
            "scope_type": "skin_image",
            "scope_key": None,
            "reason": "Broad image access should be rejected.",
        },
    )
    assert response.status_code == 422


def test_reassignment_revokes_previous_reviewers_exact_image_scope(
    client: TestClient,
) -> None:
    from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent

    admin_token, admin = _register(client, "skin-reassign-admin@example.com")
    first_token, first_reviewer = _register(client, "skin-reassign-first@example.com")
    second_token, second_reviewer = _register(client, "skin-reassign-second@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(first_reviewer.id, "reviewer")
    _set_account_role(second_reviewer.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(admin.id)
    _grant_skin_image_review_scope(first_reviewer.id, prediction.id, admin.id)
    _grant_skin_image_review_scope(second_reviewer.id, prediction.id, admin.id)

    first = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={"reviewer_id": str(first_reviewer.id), "reason": "First reviewer assignment."},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={"reviewer_id": str(second_reviewer.id), "reason": "Reassigned to another reviewer."},
    )
    assert second.status_code == 200, second.text

    db = TestingSessionLocal()
    try:
        old_scope = db.scalar(
            select(CatalogReviewerScope).where(
                CatalogReviewerScope.reviewer_id == first_reviewer.id,
                CatalogReviewerScope.scope_type == "skin_image",
                CatalogReviewerScope.scope_key == str(prediction.id),
            )
        )
        assert old_scope is not None and old_scope.revoked_at is not None
        revoke_event = db.scalar(
            select(CatalogReviewerScopeEvent).where(
                CatalogReviewerScopeEvent.reviewer_id == first_reviewer.id,
                CatalogReviewerScopeEvent.scope_type == "skin_image",
                CatalogReviewerScopeEvent.event_type == "revoked",
            )
        )
        assert revoke_event is not None
    finally:
        db.close()

    old_access = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/events",
        headers=_headers(first_token),
    )
    assert old_access.status_code == 404
    new_queue = client.get(
        "/api/v1/skin-images/review/queue",
        headers=_headers(second_token),
    )
    assert new_queue.status_code == 200
    assert [item["prediction_id"] for item in new_queue.json()] == [str(prediction.id)]


def test_skin_image_intake_requires_separate_human_review_consent(
    client: TestClient,
) -> None:
    token, _ = _register(client, "image-review-consent-required@example.com")
    form = _intake_form()
    form["review_consent"] = "false"
    response = client.post(
        "/api/v1/skin-images/intake",
        headers=_headers(token),
        data=form,
        files={"image": ("skin.png", _small_png(), "image/png")},
    )
    assert response.status_code == 422
    assert "human-review" in response.json()["detail"]


def test_owner_revoking_review_consent_revokes_assigned_reviewer_scope(
    client: TestClient,
) -> None:
    from app.models.reviewer_scope import CatalogReviewerScope
    from app.models.prediction import PredictionConsentEvent

    owner_token, owner = _register(client, "skin-review-consent-owner@example.com")
    admin_token, admin = _register(client, "skin-review-consent-admin@example.com")
    reviewer_token, reviewer = _register(client, "skin-review-consent-reviewer@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(owner.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)

    assigned = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={"reviewer_id": str(reviewer.id), "reason": "Assign for technical image review."},
    )
    assert assigned.status_code == 200, assigned.text

    revoked = client.post(
        f"/api/v1/skin-images/{prediction.id}/revoke-review-consent",
        headers=_headers(owner_token),
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["consent_status"] == "revoked"
    assert revoked.json()["reviewer_access_revoked"] is True

    queue = client.get(
        "/api/v1/skin-images/review/queue",
        headers=_headers(reviewer_token),
    )
    assert queue.status_code == 200
    assert queue.json() == []

    image = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/image",
        headers=_headers(reviewer_token),
    )
    # The assignment is cleared transactionally, so the former reviewer
    # now receives the non-disclosing "not assigned" response.
    assert image.status_code == 404

    db = TestingSessionLocal()
    try:
        image_record = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        assert image_record is not None
        assert image_record.review_status == "pending"
        assert image_record.assigned_reviewer_id is None
        unassigned = db.scalar(
            select(SkinImageReviewEvent).where(
                SkinImageReviewEvent.prediction_id == prediction.id,
                SkinImageReviewEvent.event_type == "unassigned",
                SkinImageReviewEvent.assigned_reviewer_id == reviewer.id,
            )
        )
        assert unassigned is not None
        assert "revoked human-review consent" in unassigned.reason
        scope = db.scalar(
            select(CatalogReviewerScope).where(
                CatalogReviewerScope.reviewer_id == reviewer.id,
                CatalogReviewerScope.scope_type == "skin_image",
                CatalogReviewerScope.scope_key == str(prediction.id),
            )
        )
        assert scope is not None and scope.revoked_at is not None
        consent = db.scalar(
            select(PredictionConsentEvent).where(
                PredictionConsentEvent.prediction_id == prediction.id,
                PredictionConsentEvent.purpose == "skin_image_review",
            ).order_by(PredictionConsentEvent.captured_at.desc())
        )
        assert consent is not None and consent.action == "revoked"
    finally:
        db.close()


def test_other_user_cannot_revoke_skin_image_review_consent(
    client: TestClient,
) -> None:
    from app.models.prediction import PredictionConsentEvent

    owner_token, owner = _register(client, "skin-review-consent-owner-2@example.com")
    other_token, other = _register(client, "skin-review-consent-other@example.com")
    prediction, _, _ = _prepare_skin_review_item(owner.id)

    response = client.post(
        f"/api/v1/skin-images/{prediction.id}/revoke-review-consent",
        headers=_headers(other_token),
    )
    assert response.status_code == 404

    db = TestingSessionLocal()
    try:
        latest = db.scalar(
            select(PredictionConsentEvent)
            .where(
                PredictionConsentEvent.prediction_id == prediction.id,
                PredictionConsentEvent.purpose == "skin_image_review",
            )
            .order_by(PredictionConsentEvent.captured_at.desc())
        )
        assert latest is not None and latest.action == "granted"
    finally:
        db.close()


def test_skin_image_audit_feed_is_scoped_and_identifies_event_actor(
    client: TestClient,
) -> None:
    admin_token, admin = _register(client, "skin-audit-admin@example.com")
    reviewer_token, reviewer = _register(client, "skin-audit-reviewer@example.com")
    other_token, other = _register(client, "skin-audit-other@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")
    _set_account_role(other.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(admin.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)

    assigned = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={
            "reviewer_id": str(reviewer.id),
            "reason": "Assign image for technical capture review.",
        },
    )
    assert assigned.status_code == 200, assigned.text

    reviewer_audit = client.get(
        "/api/v1/skin-images/review/audit?limit=20&offset=0",
        headers=_headers(reviewer_token),
    )
    assert reviewer_audit.status_code == 200, reviewer_audit.text
    reviewer_events = reviewer_audit.json()
    assert len(reviewer_events) == 1
    assert reviewer_events[0]["prediction_id"] == str(prediction.id)
    assert reviewer_events[0]["event_type"] == "assigned"
    assert reviewer_events[0]["actor_identity"] == admin.email
    assert reviewer_events[0]["actor_role"] == "admin"

    other_audit = client.get(
        "/api/v1/skin-images/review/audit",
        headers=_headers(other_token),
    )
    assert other_audit.status_code == 200
    assert other_audit.json() == []

    admin_audit = client.get(
        "/api/v1/skin-images/review/audit",
        headers=_headers(admin_token),
    )
    assert admin_audit.status_code == 200
    assert any(
        event["prediction_id"] == str(prediction.id)
        and event["event_type"] == "assigned"
        for event in admin_audit.json()
    )

    invalid_pagination = client.get(
        "/api/v1/skin-images/review/audit?limit=201",
        headers=_headers(admin_token),
    )
    assert invalid_pagination.status_code == 422



def test_owner_skin_image_review_status_exposes_only_safe_status_fields(
    client: TestClient,
) -> None:
    owner_token, owner = _register(client, "skin-status-owner@example.com")
    other_token, _ = _register(client, "skin-status-other@example.com")
    prediction, _, _ = _prepare_skin_review_item(owner.id)

    own = client.get(
        f"/api/v1/skin-images/{prediction.id}/review-status",
        headers=_headers(owner_token),
    )
    assert own.status_code == 200, own.text
    payload = own.json()
    assert payload["status"] == "awaiting_review"
    assert payload["status_label"] == "Awaiting technical image review"
    assert "not started yet" in payload["status_detail"]
    assert "Seek medical care independently" in payload["next_step"]
    assert payload["clinical_interpretation_performed"] is False
    assert payload["disease_prediction_performed"] is False
    assert set(payload) == {
        "prediction_id", "status", "status_label", "status_detail", "next_step", "status_at",
        "clinical_interpretation_performed", "disease_prediction_performed",
    }

    forbidden = client.get(
        f"/api/v1/skin-images/{prediction.id}/review-status",
        headers=_headers(other_token),
    )
    assert forbidden.status_code == 404


def test_owner_skin_image_review_status_reflects_assignment_and_revocation(
    client: TestClient,
) -> None:
    owner_token, owner = _register(client, "skin-status-assignment-owner@example.com")
    admin_token, admin = _register(client, "skin-status-assignment-admin@example.com")
    reviewer_token, reviewer = _register(client, "skin-status-assignment-reviewer@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(owner.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)

    assigned = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={"reviewer_id": str(reviewer.id), "reason": "Assign for technical review."},
    )
    assert assigned.status_code == 200, assigned.text
    status_response = client.get(
        f"/api/v1/skin-images/{prediction.id}/review-status",
        headers=_headers(owner_token),
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "assigned"
    assert "assigned_reviewer" not in status_response.json()
    assert "reason" not in status_response.json()

    revoked = client.post(
        f"/api/v1/skin-images/{prediction.id}/revoke-review-consent",
        headers=_headers(owner_token),
    )
    assert revoked.status_code == 200
    after_revoke = client.get(
        f"/api/v1/skin-images/{prediction.id}/review-status",
        headers=_headers(owner_token),
    )
    assert after_revoke.status_code == 200
    assert after_revoke.json()["status"] == "review_access_withdrawn"
    assert after_revoke.json()["status_at"] is None



def test_owner_review_status_is_minimal_and_never_exposes_reviewer_or_storage_data(
    client: TestClient,
) -> None:
    owner_token, owner = _register(client, "skin-status-minimal-owner@example.com")
    other_token, _ = _register(client, "skin-status-minimal-other@example.com")
    prediction, _, _ = _prepare_skin_review_item(owner.id)

    response = client.get(
        f"/api/v1/skin-images/{prediction.id}/review-status",
        headers=_headers(owner_token),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["prediction_id"] == str(prediction.id)
    assert payload["status"] == "awaiting_review"
    assert isinstance(payload["status_label"], str)
    assert isinstance(payload["status_detail"], str)
    assert isinstance(payload["next_step"], str)
    assert payload["status_at"] is not None
    assert payload["clinical_interpretation_performed"] is False
    assert payload["disease_prediction_performed"] is False
    forbidden_fields = {
        "object_key", "image_sha256", "assigned_reviewer_id",
        "reviewer_identity", "actor_identity", "reason", "audit_events",
        "image_url", "image_bytes",
    }
    assert forbidden_fields.isdisjoint(payload)
    assert response.status_code == 200

    not_owner = client.get(
        f"/api/v1/skin-images/{prediction.id}/review-status",
        headers=_headers(other_token),
    )
    assert not_owner.status_code == 404

def test_skin_image_history_delete_removes_private_object_and_preserves_review_audit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import predictions
    from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
    token, user = _register(client, "image-delete-success@example.com")
    reviewer_token, reviewer = _register(client, "image-delete-reviewer@example.com")
    _set_account_role(reviewer.id, "reviewer")
    item, key, _ = _stored_image_for_user(user.id)
    db = TestingSessionLocal()
    try:
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id))
        assert image is not None
        db.add(SkinImageReviewEvent(
            prediction_id=item.id, image_analysis_id=image.id,
            event_type="assigned", actor_id=user.id,
            assigned_reviewer_id=reviewer.id,
            reason="Assignment recorded for audit.",
        ))
        db.add(CatalogReviewerScope(
            reviewer_id=reviewer.id,
            scope_type="skin_image",
            scope_key=str(item.id),
            granted_by=user.id,
            grant_reason="Owner approved exact image review access.",
        ))
        db.commit()
    finally:
        db.close()
    storage = _FakeIntakeStorage()
    storage.objects[key] = (b"private-image", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)
    response = client.delete(f"/api/v1/predictions/history/{item.id}", headers=_headers(token))
    assert response.status_code == 204
    assert key not in storage.objects
    reviewer_history = client.get(
        f"/api/v1/skin-images/review/{item.id}/events",
        headers=_headers(reviewer_token),
    )
    assert reviewer_history.status_code == 404
    db = TestingSessionLocal()
    try:
        assert db.get(Prediction, item.id) is None
        events = list(db.scalars(select(SkinImageReviewEvent).where(SkinImageReviewEvent.prediction_id == item.id)).all())
        assert len(events) == 1 and events[0].event_type == "assigned"
        scope = db.scalar(select(CatalogReviewerScope).where(
            CatalogReviewerScope.reviewer_id == reviewer.id,
            CatalogReviewerScope.scope_type == "skin_image",
            CatalogReviewerScope.scope_key == str(item.id),
        ))
        assert scope is not None and scope.revoked_at is not None
        assert scope.revoked_by == user.id
        scope_event = db.scalar(select(CatalogReviewerScopeEvent).where(
            CatalogReviewerScopeEvent.scope_id == scope.id,
            CatalogReviewerScopeEvent.event_type == "revoked",
        ))
        assert scope_event is not None and scope_event.operator_id == user.id
    finally:
        db.close()


def test_image_history_consent_revocation_also_revokes_reviewer_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import predictions
    from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent

    owner_token, owner = _register(client, "image-history-scope-owner@example.com")
    _, reviewer = _register(client, "image-history-scope-reviewer@example.com")
    _set_account_role(reviewer.id, "reviewer")
    item, key, _ = _stored_image_for_user(owner.id)

    db = TestingSessionLocal()
    try:
        image = db.scalar(
            select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id)
        )
        assert image is not None
        image.review_status = "assigned"
        image.assigned_reviewer_id = reviewer.id
        scope = CatalogReviewerScope(
            reviewer_id=reviewer.id,
            scope_type="skin_image",
            scope_key=str(item.id),
            granted_by=owner.id,
            grant_reason="Owner approved exact image review access.",
        )
        db.add(scope)
        db.commit()
        scope_id = scope.id
    finally:
        db.close()

    storage = _FakeIntakeStorage()
    storage.objects[key] = (b"private-image", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)

    response = client.post(
        f"/api/v1/predictions/history/{item.id}/revoke-consent",
        headers=_headers(owner_token),
    )
    assert response.status_code == 200, response.text
    assert key not in storage.objects

    db = TestingSessionLocal()
    try:
        revoked_scope = db.get(CatalogReviewerScope, scope_id)
        assert revoked_scope is not None
        assert revoked_scope.revoked_at is not None
        assert revoked_scope.revoked_by == owner.id
        event = db.scalar(
            select(CatalogReviewerScopeEvent).where(
                CatalogReviewerScopeEvent.scope_id == scope_id,
                CatalogReviewerScopeEvent.event_type == "revoked",
            )
        )
        assert event is not None
        assert event.operator_id == owner.id
        assert event.reason == "Image-history consent revoked; reviewer access revoked."
    finally:
        db.close()


def test_repeated_image_history_consent_revocation_does_not_duplicate_audit_event(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import predictions

    token, user = _register(client, "image-revoke-repeat@example.com")
    item, key, _ = _stored_image_for_user(user.id)
    storage = _FakeIntakeStorage()
    storage.objects[key] = (b"private-image", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)

    first = client.post(
        f"/api/v1/predictions/history/{item.id}/revoke-consent",
        headers=_headers(token),
    )
    second = client.post(
        f"/api/v1/predictions/history/{item.id}/revoke-consent",
        headers=_headers(token),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert key not in storage.objects
    db = TestingSessionLocal()
    try:
        events = list(db.scalars(
            select(PredictionConsentEvent).where(
                PredictionConsentEvent.prediction_id == item.id,
                PredictionConsentEvent.purpose == "skin_image_history",
            ).order_by(PredictionConsentEvent.captured_at, PredictionConsentEvent.id)
        ).all())
        assert [event.action for event in events] == ["granted", "revoked"]
    finally:
        db.close()


def test_image_history_consent_revocation_keeps_consent_active_until_delete_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import predictions
    token, user = _register(client, "image-revoke-retry@example.com")
    item, key, _ = _stored_image_for_user(user.id)

    class FlakyStorage(_FakeIntakeStorage):
        def __init__(self):
            super().__init__()
            self.fail = True
            self.calls = 0
        def delete_private(self, object_key: str) -> None:
            self.calls += 1
            if self.fail:
                raise OSError("temporary private-storage outage")
            super().delete_private(object_key)

    storage = FlakyStorage()
    storage.objects[key] = (b"private-image", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)

    first = client.post(
        f"/api/v1/predictions/history/{item.id}/revoke-consent",
        headers=_headers(token),
    )
    assert first.status_code == 503
    assert "remains active" in first.json()["detail"]
    db = TestingSessionLocal()
    try:
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id))
        assert image is not None and image.storage_status == "deletion_pending"
        assert image.deletion_requested_at is not None
        latest = db.scalar(
            select(PredictionConsentEvent)
            .where(PredictionConsentEvent.prediction_id == item.id, PredictionConsentEvent.purpose == "skin_image_history")
            .order_by(PredictionConsentEvent.captured_at.desc(), PredictionConsentEvent.id.desc())
        )
        assert latest is not None and latest.action == "granted"
    finally:
        db.close()

    storage.fail = False
    second = client.post(
        f"/api/v1/predictions/history/{item.id}/revoke-consent",
        headers=_headers(token),
    )
    assert second.status_code == 200 and second.json()["consent_revoked"] is True
    assert storage.calls == 2 and key not in storage.objects
    db = TestingSessionLocal()
    try:
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id))
        assert image is not None and image.storage_status == "deleted"
        latest = db.scalar(
            select(PredictionConsentEvent)
            .where(PredictionConsentEvent.prediction_id == item.id, PredictionConsentEvent.purpose == "skin_image_history")
            .order_by(PredictionConsentEvent.captured_at.desc(), PredictionConsentEvent.id.desc())
        )
        assert latest is not None and latest.action == "revoked"
    finally:
        db.close()

def test_skin_image_history_delete_failure_keeps_retry_marker_and_can_retry(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import predictions
    token, user = _register(client, "image-delete-retry@example.com")
    item, key, _ = _stored_image_for_user(user.id)
    class FlakyStorage(_FakeIntakeStorage):
        def __init__(self):
            super().__init__()
            self.fail = True
            self.calls = 0
        def delete_private(self, object_key: str) -> None:
            self.calls += 1
            if self.fail:
                raise OSError("temporary object-storage outage")
            super().delete_private(object_key)
    storage = FlakyStorage()
    storage.objects[key] = (b"private-image", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)
    first = client.delete(f"/api/v1/predictions/history/{item.id}", headers=_headers(token))
    assert first.status_code == 503 and "pending" in first.json()["detail"].lower()
    db = TestingSessionLocal()
    try:
        retained = db.get(Prediction, item.id)
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id))
        assert retained is not None and image is not None
        assert image.storage_status == "deletion_pending" and image.deletion_requested_at is not None
    finally:
        db.close()
    storage.fail = False
    second = client.delete(f"/api/v1/predictions/history/{item.id}", headers=_headers(token))
    assert second.status_code == 204 and storage.calls == 2
    assert key not in storage.objects
    db = TestingSessionLocal()
    try:
        assert db.get(Prediction, item.id) is None
    finally:
        db.close()


@pytest.mark.parametrize("storage_status", ["pending_upload", "failed"])
def test_incomplete_skin_image_upload_can_be_safely_deleted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    storage_status: str,
) -> None:
    """Idempotent object deletion cleans up writes with an ambiguous outcome."""
    from app.api.v1 import predictions

    token, user = _register(client, f"image-delete-{storage_status}@example.com")
    item = _prediction(user.id, modality="skin_image")
    key = "skin-images/33333333333333333333333333333333.png"
    db = TestingSessionLocal()
    try:
        db.add(SkinImageAnalysis(
            prediction_id=item.id,
            object_key=key,
            content_type="image/png",
            image_sha256="c" * 64,
            storage_status=storage_status,
        ))
        db.commit()
    finally:
        db.close()

    storage = _FakeIntakeStorage()
    # A failed put may have partially succeeded before the adapter raised.
    storage.objects[key] = (b"possibly-partial-object", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)

    response = client.delete(
        f"/api/v1/predictions/history/{item.id}",
        headers=_headers(token),
    )
    assert response.status_code == 204
    assert key not in storage.objects

    db = TestingSessionLocal()
    try:
        assert db.get(Prediction, item.id) is None
    finally:
        db.close()


def test_skin_image_history_delete_is_blocked_for_unknown_storage_state(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import predictions
    token, user = _register(client, "image-delete-unknown@example.com")
    item = _prediction(user.id, modality="skin_image")
    db = TestingSessionLocal()
    try:
        db.add(SkinImageAnalysis(
            prediction_id=item.id,
            object_key="skin-images/22222222222222222222222222222222.png",
            content_type="image/png", image_sha256="b" * 64,
            storage_status="unknown",
        ))
        db.commit()
    finally:
        db.close()
    storage = _FakeIntakeStorage()
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)
    response = client.delete(f"/api/v1/predictions/history/{item.id}", headers=_headers(token))
    assert response.status_code == 409 and storage.objects == {}
    db = TestingSessionLocal()
    try:
        assert db.get(Prediction, item.id) is not None
    finally:
        db.close()


def test_other_user_cannot_revoke_skin_image_history_consent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import predictions
    owner_token, owner = _register(client, "image-history-owner@example.com")
    other_token, _ = _register(client, "image-history-other@example.com")
    item, key, _ = _stored_image_for_user(owner.id)
    storage = _FakeIntakeStorage()
    storage.objects[key] = (b"private-image", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)
    response = client.post(f"/api/v1/predictions/history/{item.id}/revoke-consent", headers=_headers(other_token))
    assert response.status_code == 404 and key in storage.objects
    db = TestingSessionLocal()
    try:
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id))
        assert image is not None and image.storage_status == "stored"
        latest = db.scalar(select(PredictionConsentEvent).where(PredictionConsentEvent.prediction_id == item.id, PredictionConsentEvent.purpose == "skin_image_history").order_by(PredictionConsentEvent.captured_at.desc(), PredictionConsentEvent.id.desc()))
        assert latest is not None and latest.action == "granted"
    finally:
        db.close()


def test_image_history_consent_revocation_blocks_unknown_storage_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import predictions
    token, user = _register(client, "image-history-unknown@example.com")
    item, key, _ = _stored_image_for_user(user.id)
    db = TestingSessionLocal()
    try:
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id))
        assert image is not None
        image.storage_status = "unknown"
        db.commit()
    finally:
        db.close()
    storage = _FakeIntakeStorage()
    storage.objects[key] = (b"private-image", "image/png")
    monkeypatch.setattr(predictions, "build_skin_image_storage", lambda: storage)
    response = client.post(f"/api/v1/predictions/history/{item.id}/revoke-consent", headers=_headers(token))
    assert response.status_code == 409 and key in storage.objects
    db = TestingSessionLocal()
    try:
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == item.id))
        assert image is not None and image.storage_status == "unknown"
        latest = db.scalar(select(PredictionConsentEvent).where(PredictionConsentEvent.prediction_id == item.id, PredictionConsentEvent.purpose == "skin_image_history").order_by(PredictionConsentEvent.captured_at.desc(), PredictionConsentEvent.id.desc()))
        assert latest is not None and latest.action == "granted"
    finally:
        db.close()

def test_retention_deleted_image_blocks_reviewer_even_with_active_scope_and_consent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images
    from app.models.prediction import SkinImageReviewEvent

    reviewer_token, reviewer = _register(client, "skin-review-expired@example.com")
    admin_token, admin = _register(client, "skin-review-expired-admin@example.com")
    _set_account_role(reviewer.id, "reviewer")
    _set_account_role(admin.id, "admin")
    prediction, _, _ = _prepare_skin_review_item(reviewer.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)

    db = TestingSessionLocal()
    try:
        image = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        image.storage_status = "deleted"
        image.deleted_at = datetime.now(timezone.utc)
        image.review_status = "assigned"
        image.assigned_reviewer_id = reviewer.id
        db.commit()
    finally:
        db.close()

    def storage_must_not_be_opened():
        raise AssertionError("Deleted image must be rejected before storage access.")

    monkeypatch.setattr(skin_images, "build_skin_image_storage", storage_must_not_be_opened)
    response = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/image",
        headers=_headers(reviewer_token),
    )
    assert response.status_code == 404

    owner_status = client.get(
        f"/api/v1/skin-images/{prediction.id}/review-status",
        headers=_headers(reviewer_token),
    )
    assert owner_status.status_code == 200, owner_status.text
    status_payload = owner_status.json()
    assert status_payload["status"] == "submission_unavailable"
    assert status_payload["clinical_interpretation_performed"] is False
    assert status_payload["disease_prediction_performed"] is False
    assert set(status_payload) == {
        "prediction_id", "status", "status_label", "status_detail", "next_step",
        "status_at", "clinical_interpretation_performed", "disease_prediction_performed",
    }

    db = TestingSessionLocal()
    try:
        access_events = db.scalars(
            select(SkinImageReviewEvent).where(
                SkinImageReviewEvent.prediction_id == prediction.id,
                SkinImageReviewEvent.event_type == "image_accessed",
            )
        ).all()
        assert access_events == []
    finally:
        db.close()


def test_revoked_review_consent_blocks_reviewer_image_storage_access(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import skin_images
    from app.models.prediction import SkinImageReviewEvent

    owner_token, owner = _register(client, "skin-review-consent-owner@example.com")
    reviewer_token, reviewer = _register(client, "skin-review-consent-reviewer@example.com")
    admin_token, admin = _register(client, "skin-review-consent-admin@example.com")
    _set_account_role(reviewer.id, "reviewer")
    _set_account_role(admin.id, "admin")
    prediction, key, _ = _prepare_skin_review_item(owner.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)

    db = TestingSessionLocal()
    try:
        image = db.scalar(select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == prediction.id))
        assert image is not None
        image.review_status = "assigned"
        image.assigned_reviewer_id = reviewer.id
        review_grant = db.scalar(select(PredictionConsentEvent).where(
            PredictionConsentEvent.prediction_id == prediction.id,
            PredictionConsentEvent.purpose == "skin_image_review",
            PredictionConsentEvent.action == "granted",
        ))
        assert review_grant is not None
        review_grant.action = "revoked"
        db.commit()
    finally:
        db.close()

    def storage_must_not_be_opened():
        raise AssertionError("Revoked review consent must block private storage access.")

    monkeypatch.setattr(skin_images, "build_skin_image_storage", storage_must_not_be_opened)
    response = client.get(
        f"/api/v1/skin-images/review/{prediction.id}/image",
        headers=_headers(reviewer_token),
    )
    assert response.status_code == 403
    assert "consent" in response.json()["detail"].lower()

    db = TestingSessionLocal()
    try:
        access_events = db.scalars(select(SkinImageReviewEvent).where(
            SkinImageReviewEvent.prediction_id == prediction.id,
            SkinImageReviewEvent.event_type == "image_accessed",
        )).all()
        assert access_events == []
    finally:
        db.close()


def test_account_data_export_is_owner_scoped_and_excludes_internal_secrets(client: TestClient) -> None:
    token, owner = _register(client, "export-owner@example.com")
    _, other = _register(client, "export-other@example.com")
    own = _prediction(owner.id, input_text="my private symptom narrative")
    _prediction(other.id, input_text="someone else's private narrative")
    db = TestingSessionLocal()
    try:
        disease = Disease(code="EXPORT_CONDITION", name="Export Condition", is_active=True)
        db.add(disease)
        db.flush()
        db.add(PredictionResult(
            prediction_id=own.id, disease_id=disease.id, rank=1,
            probability=0.375, explanation="A source-backed explanation for the owner.",
        ))
        db.add(SkinImageAnalysis(
            prediction_id=own.id,
            object_key="skin-images/" + "a" * 32 + ".jpg",
            content_type="image/jpeg", image_sha256="b" * 64,
            storage_status="deleted", review_status="unable_to_assess",
        ))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/auth/me/export", headers=_headers(token))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "attachment;" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["account"]["email"] == "export-owner@example.com"
    assert len(payload["predictions"]) == 1
    exported = payload["predictions"][0]
    assert exported["id"] == str(own.id)
    assert exported["input_text"] == "my private symptom narrative"
    assert exported["results"][0]["disease_code"] == "EXPORT_CONDITION"
    assert exported["image_metadata"]["content_type"] == "image/jpeg"
    assert "object_key" not in response.text
    assert "skin-images/" not in response.text
    assert "password_hash" not in response.text
    assert "access_token" not in response.text
    assert "someone else's private narrative" not in response.text


def test_account_data_export_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me/export").status_code == 401

def test_deleted_image_is_excluded_from_queue_and_rejects_assignment_and_decision(
    client: TestClient,
) -> None:
    """A stale assignment cannot revive a deleted private image."""
    admin_token, admin = _register(client, "deleted-review-admin@example.com")
    reviewer_token, reviewer = _register(client, "deleted-review-reviewer@example.com")
    owner_token, owner = _register(client, "deleted-review-owner@example.com")
    _set_account_role(admin.id, "admin")
    _set_account_role(reviewer.id, "reviewer")
    prediction, _, _ = _prepare_skin_review_item(owner.id)
    _grant_skin_image_review_scope(reviewer.id, prediction.id, admin.id)

    db = TestingSessionLocal()
    try:
        image = db.scalar(
            select(SkinImageAnalysis).where(
                SkinImageAnalysis.prediction_id == prediction.id
            )
        )
        assert image is not None
        image.storage_status = "deleted"
        image.deleted_at = datetime.now(timezone.utc)
        image.review_status = "assigned"
        image.assigned_reviewer_id = reviewer.id
        image.assigned_by = admin.id
        db.commit()
    finally:
        db.close()

    queue = client.get(
        "/api/v1/skin-images/review/queue",
        headers=_headers(reviewer_token),
    )
    assert queue.status_code == 200
    assert all(row["prediction_id"] != str(prediction.id) for row in queue.json())

    assignment = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/assign",
        headers=_headers(admin_token),
        json={
            "reviewer_id": str(reviewer.id),
            "reason": "Deleted image must not be reassigned.",
        },
    )
    assert assignment.status_code == 409

    decision = client.post(
        f"/api/v1/skin-images/review/{prediction.id}/decision",
        headers=_headers(reviewer_token),
        json={
            "outcome": "capture_adequate",
            "reason": "Deleted image cannot receive a review decision.",
        },
    )
    assert decision.status_code == 409

