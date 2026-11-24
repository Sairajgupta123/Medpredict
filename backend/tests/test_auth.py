"""Authentication endpoint tests using an isolated in-memory SQLite database."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app import models  # noqa: F401 - register ORM metadata

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
    """Create a fresh schema and dependency override for each test."""
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


def _signed_test_token(**overrides: object) -> str:
    from app.core.config import get_settings

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "type": "access",
        "ver": 0,
        "iss": "medipredict-api",
    }
    payload.update(overrides)
    return jwt.encode(payload, get_settings().app_secret_key, algorithm="HS256")


def test_expired_access_token_is_rejected() -> None:
    from app.core.security import decode_access_token

    now = datetime.now(timezone.utc)
    token = _signed_test_token(
        iat=now - timedelta(minutes=10),
        exp=now - timedelta(minutes=1),
    )

    assert decode_access_token(token) is None


def test_access_token_with_invalid_signature_is_rejected() -> None:
    from app.core.security import decode_access_token

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "type": "access",
        "iss": "medipredict-api",
    }
    token = jwt.encode(payload, "not-the-application-secret-key-32-bytes", algorithm="HS256")

    assert decode_access_token(token) is None


def test_non_access_jwt_type_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(type="refresh")

    assert decode_access_token(token) is None


def test_token_from_untrusted_issuer_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(iss="untrusted-service")

    assert decode_access_token(token) is None


def test_access_token_without_version_claim_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(ver=None)
    assert decode_access_token(token) is None


def test_access_token_with_invalid_version_type_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(ver=True)
    assert decode_access_token(token) is None


def test_password_reset_request_uses_generic_response_for_unknown_email(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth

    def unexpected_delivery(*args, **kwargs):
        raise AssertionError("No email should be sent for an unknown account.")

    monkeypatch.setattr(auth, "send_password_reset_email", unexpected_delivery)
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "nobody@example.com"},
    )

    assert response.status_code == 202
    assert response.json() == {
        "message": (
            "If an account exists for this email, password reset instructions "
            "will be sent."
        )
    }


def test_password_reset_request_sends_email_without_returning_token(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth

    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "recover@example.com", "password": "OldPassword123!"},
    )
    assert registration.status_code == 201

    delivered = {}

    def capture_delivery(recipient: str, raw_token: str) -> None:
        delivered["recipient"] = recipient
        delivered["token"] = raw_token

    monkeypatch.setattr(auth, "send_password_reset_email", capture_delivery)
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "RECOVER@example.com"},
    )

    assert response.status_code == 202
    assert delivered["recipient"] == "recover@example.com"
    assert delivered["token"] not in response.text


def test_password_reset_confirmation_changes_password_and_consumes_token(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth

    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "change-password@example.com", "password": "OldPassword123!"},
    )
    assert registration.status_code == 201
    old_access_token = registration.json()["access_token"]
    old_session = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {old_access_token}"},
    )
    assert old_session.status_code == 200

    delivered = {}

    def capture_delivery(recipient: str, raw_token: str) -> None:
        delivered["token"] = raw_token

    monkeypatch.setattr(auth, "send_password_reset_email", capture_delivery)
    request = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "change-password@example.com"},
    )
    assert request.status_code == 202

    confirmation = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": delivered["token"],
            "new_password": "NewPassword456!",
        },
    )
    assert confirmation.status_code == 200

    revoked_session = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {old_access_token}"},
    )
    assert revoked_session.status_code == 401

    old_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "change-password@example.com",
            "password": "OldPassword123!",
        },
    )
    new_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "change-password@example.com",
            "password": "NewPassword456!",
        },
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200

    replay = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": delivered["token"],
            "new_password": "AnotherPassword789!",
        },
    )
    assert replay.status_code == 400


def test_password_reset_confirmation_rejects_invalid_token(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "x" * 40, "new_password": "NewPassword456!"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "The password reset link is invalid or has expired."
    )


def test_password_reset_delivery_failure_does_not_leak_account_existence(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth

    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "delivery-failure@example.com", "password": "OldPassword123!"},
    )
    assert registration.status_code == 201

    delivered = {}

    def fail_delivery(recipient: str, raw_token: str) -> None:
        delivered["token"] = raw_token
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(auth, "send_password_reset_email", fail_delivery)
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "delivery-failure@example.com"},
    )

    assert response.status_code == 202
    assert "token" not in response.text.lower()
    assert "token" in delivered

    unusable_token = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": delivered["token"],
            "new_password": "NewPassword456!",
        },
    )
    assert unusable_token.status_code == 400


def test_logout_revokes_current_and_other_account_access_tokens(
    client: TestClient,
) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "logout@example.com", "password": "StrongPass123!"},
    )
    assert registration.status_code == 201
    first_token = registration.json()["access_token"]

    second_login = client.post(
        "/api/v1/auth/login",
        json={"email": "logout@example.com", "password": "StrongPass123!"},
    )
    assert second_login.status_code == 200
    second_token = second_login.json()["access_token"]

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {
        "message": "You have been logged out successfully."
    }

    for token in (first_token, second_token):
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    fresh_login = client.post(
        "/api/v1/auth/login",
        json={"email": "logout@example.com", "password": "StrongPass123!"},
    )
    assert fresh_login.status_code == 200
    fresh_profile = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {fresh_login.json()['access_token']}"
        },
    )
    assert fresh_profile.status_code == 200


def test_logout_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 401


def test_register_login_and_read_profile(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "  Student@Example.com ",
            "password": "StrongPass123!",
            "display_name": "Student",
        },
    )
    assert registration.status_code == 201
    registered = registration.json()
    assert registered["user"]["email"] == "student@example.com"
    assert registered["token_type"] == "bearer"
    assert "password_hash" not in registered["user"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "STUDENT@example.com", "password": "StrongPass123!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    profile = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile.status_code == 200
    assert profile.json()["email"] == "student@example.com"


def test_duplicate_registration_is_rejected(client: TestClient) -> None:
    payload = {"email": "duplicate@example.com", "password": "StrongPass123!"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409


def test_login_uses_generic_error_for_invalid_credentials(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": "WrongPass123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_profile_requires_valid_bearer_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.token.value"},
    ).status_code == 401


def test_weak_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_password_is_stored_as_a_hash(client: TestClient) -> None:
    from app.core.security import verify_password
    from app.models.user import User

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "hash@example.com", "password": "StrongPass123!"},
    )
    assert response.status_code == 201

    db = TestingSessionLocal()
    try:
        stored_user = db.query(User).filter_by(email="hash@example.com").one()
        assert stored_user.password_hash != "StrongPass123!"
        assert verify_password("StrongPass123!", stored_user.password_hash)
    finally:
        db.close()


def test_inactive_account_cannot_log_in(client: TestClient) -> None:
    from app.core.security import hash_password
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        db.add(
            User(
                email="inactive@example.com",
                password_hash=hash_password("StrongPass123!"),
                is_active=False,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "StrongPass123!"},
    )
    assert response.status_code == 401


def test_existing_access_token_is_rejected_after_account_deactivation(
    client: TestClient,
) -> None:
    """A previously issued token must stop working once its account is disabled."""
    from app.models.user import User

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "deactivated-token@example.com",
            "password": "StrongPass123!",
        },
    )
    assert registration.status_code == 201
    token = registration.json()["access_token"]
    authorization = {"Authorization": f"Bearer {token}"}

    before_deactivation = client.get("/api/v1/auth/me", headers=authorization)
    assert before_deactivation.status_code == 200

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter_by(
            email="deactivated-token@example.com"
        ).one()
        user.is_active = False
        db.commit()
    finally:
        db.close()

    after_deactivation = client.get("/api/v1/auth/me", headers=authorization)
    assert after_deactivation.status_code == 401
    assert after_deactivation.headers["www-authenticate"] == "Bearer"


def test_user_can_update_own_display_name(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "profile@example.com", "password": "StrongPass123!"},
    )
    token = registration.json()["access_token"]

    response = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "  MediPredict Student  "},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "MediPredict Student"


def test_user_can_clear_display_name(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "clearname@example.com",
            "password": "StrongPass123!",
            "display_name": "Old Name",
        },
    )
    token = registration.json()["access_token"]

    response = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": None},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] is None


def test_profile_update_requires_authentication(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/auth/me",
        json={"display_name": "No Token"},
    )
    assert response.status_code == 401


def test_profile_update_rejects_blank_name(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "blankname@example.com", "password": "StrongPass123!"},
    )
    token = registration.json()["access_token"]

    response = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "   "},
    )
    assert response.status_code == 422


def test_profile_update_rejects_empty_payload(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "emptyprofile@example.com", "password": "StrongPass123!"},
    )
    token = registration.json()["access_token"]

    response = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert response.status_code == 422

def test_reviewer_provisioning_cli_updates_role_and_writes_audit(
    client: TestClient, monkeypatch
) -> None:
    import sys

    from app.core.security import hash_password
    from app.models.user import RoleProvisioningEvent, User
    from scripts import provision_catalog_reviewer

    monkeypatch.setattr(
        provision_catalog_reviewer, "SessionLocal", TestingSessionLocal
    )
    db = TestingSessionLocal()
    try:
        db.add(
            User(
                email="reviewer-provision@example.com",
                password_hash=hash_password("StrongPass123!"),
                email_verified=True,
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setenv(
        "MEDIPREDICT_ROLE_PROVISIONING_OPERATOR", "operations@example.org"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "provision_catalog_reviewer",
            "--email",
            "reviewer-provision@example.com",
            "--role",
            "reviewer",
            "--reason",
            "Verified appointment and scope.",
        ],
    )
    monkeypatch.setattr(
        "builtins.input", lambda _: "reviewer-provision@example.com"
    )

    assert provision_catalog_reviewer.main() == 0

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter_by(email="reviewer-provision@example.com").one()
        event = (
            db.query(RoleProvisioningEvent)
            .filter_by(target_user_id=user.id)
            .one()
        )
        assert user.role == "reviewer"
        assert event.previous_role == "patient"
        assert event.new_role == "reviewer"
        assert event.operator_identity == "operations@example.org"
        assert event.reason == "Verified appointment and scope."
    finally:
        db.close()


def test_reviewer_provisioning_cli_requires_verified_email(
    client: TestClient, monkeypatch, capsys
) -> None:
    import sys

    from app.core.security import hash_password
    from app.models.user import User
    from scripts import provision_catalog_reviewer

    monkeypatch.setattr(
        provision_catalog_reviewer, "SessionLocal", TestingSessionLocal
    )
    db = TestingSessionLocal()
    try:
        db.add(
            User(
                email="unverified-reviewer@example.com",
                password_hash=hash_password("StrongPass123!"),
                email_verified=False,
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setenv(
        "MEDIPREDICT_ROLE_PROVISIONING_OPERATOR", "operations@example.org"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "provision_catalog_reviewer",
            "--email",
            "unverified-reviewer@example.com",
            "--role",
            "reviewer",
            "--reason",
            "Verified appointment and scope.",
        ],
    )

    assert provision_catalog_reviewer.main() == 1
    assert "verified account email" in capsys.readouterr().err

def test_reviewer_provisioning_cli_cannot_modify_admin_accounts(
    client: TestClient, monkeypatch, capsys
) -> None:
    import sys

    from app.core.security import hash_password
    from app.models.user import User
    from scripts import provision_catalog_reviewer

    monkeypatch.setattr(
        provision_catalog_reviewer, "SessionLocal", TestingSessionLocal
    )
    db = TestingSessionLocal()
    try:
        db.add(
            User(
                email="protected-admin@example.com",
                password_hash=hash_password("StrongPass123!"),
                email_verified=True,
                role="admin",
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setenv(
        "MEDIPREDICT_ROLE_PROVISIONING_OPERATOR", "operations@example.org"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "provision_catalog_reviewer",
            "--email",
            "protected-admin@example.com",
            "--role",
            "patient",
            "--reason",
            "Attempted role change test.",
        ],
    )

    assert provision_catalog_reviewer.main() == 1
    assert "Admin accounts cannot be changed" in capsys.readouterr().err

    db = TestingSessionLocal()
    try:
        account = db.query(User).filter_by(email="protected-admin@example.com").one()
        assert account.role == "admin"
    finally:
        db.close()

def test_reviewer_cannot_be_demoted_while_active_catalog_scopes_remain(
    client: TestClient, monkeypatch, capsys
) -> None:
    import sys

    from app.core.security import hash_password
    from app.models.reviewer_scope import CatalogReviewerScope
    from app.models.user import User
    from scripts import provision_catalog_reviewer

    monkeypatch.setattr(
        provision_catalog_reviewer, "SessionLocal", TestingSessionLocal
    )
    db = TestingSessionLocal()
    try:
        reviewer = User(
            email="scoped-reviewer-demotion@example.com",
            password_hash=hash_password("StrongPass123!"),
            email_verified=True,
            role="reviewer",
        )
        db.add(reviewer)
        db.flush()
        db.add(
            CatalogReviewerScope(
                reviewer_id=reviewer.id,
                scope_type="disease",
                scope_key=None,
                granted_by=reviewer.id,
                grant_reason="Test reviewer scope assignment.",
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setenv(
        "MEDIPREDICT_ROLE_PROVISIONING_OPERATOR", "operations@example.org"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "provision_catalog_reviewer",
            "--email",
            "scoped-reviewer-demotion@example.com",
            "--role",
            "patient",
            "--reason",
            "Reviewer access is being revoked.",
        ],
    )

    assert provision_catalog_reviewer.main() == 1
    assert "Revoke all active catalog scopes" in capsys.readouterr().err

    db = TestingSessionLocal()
    try:
        account = db.query(User).filter_by(
            email="scoped-reviewer-demotion@example.com"
        ).one()
        assert account.role == "reviewer"
    finally:
        db.close()

def test_access_token_with_malformed_subject_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(sub="not-a-uuid")
    assert decode_access_token(token) is None


def test_access_token_with_negative_version_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(ver=-1)
    assert decode_access_token(token) is None


def test_access_token_with_future_issued_at_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(iat=datetime.now(timezone.utc) + timedelta(minutes=10))
    assert decode_access_token(token) is None


def test_login_rate_limit_is_enforced_per_normalized_email(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth

    monkeypatch.setattr(auth, "verify_password", lambda *_: True)
    payload = {"email": "TARGET@example.com", "password": "WrongPassword123!"}
    for _ in range(10):
        response = client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 401

    # Move the active window forward to prove Retry-After reports only its remainder.
    from sqlalchemy import select, update

    from app.models.auth_rate_limit import AuthRateLimitBucket

    db = TestingSessionLocal()
    try:
        bucket = db.scalar(select(AuthRateLimitBucket))
        assert bucket is not None
        db.execute(
            update(AuthRateLimitBucket)
            .where(AuthRateLimitBucket.bucket_key == bucket.bucket_key)
            .values(window_started_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        )
        db.commit()
    finally:
        db.close()

    limited = client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.com", "password": "WrongPassword123!"},
    )
    assert limited.status_code == 429
    assert 595 <= int(limited.headers["retry-after"]) <= 600


def test_password_reset_request_rate_limit_keeps_generic_responses(
    client: TestClient,
) -> None:
    payload = {"email": "unknown-reset-target@example.com"}
    for _ in range(3):
        response = client.post(
            "/api/v1/auth/password-reset/request", json=payload
        )
        assert response.status_code == 202
        assert "If an account exists" in response.json()["message"]

    limited = client.post(
        "/api/v1/auth/password-reset/request", json=payload
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"


def test_registration_rate_limit_is_enforced_per_email(client: TestClient) -> None:
    payload = {"email": "limited-register@example.com", "password": "StrongPass123!"}
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    for _ in range(4):
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 409

    limited = client.post("/api/v1/auth/register", json=payload)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"



def test_rate_limit_window_resets_after_expiry_and_stores_only_digest(
    client: TestClient, monkeypatch
) -> None:
    from datetime import timedelta, timezone

    from sqlalchemy import select, update

    from app.api.v1 import auth
    from app.models.auth_rate_limit import AuthRateLimitBucket

    monkeypatch.setattr(auth, "verify_password", lambda *_: True)
    payload = {"email": "Window-Reset@example.com", "password": "WrongPassword123!"}
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401

    db = TestingSessionLocal()
    try:
        bucket = db.scalar(select(AuthRateLimitBucket))
        assert bucket is not None
        assert "window-reset@example.com" not in bucket.bucket_key
        db.execute(
            update(AuthRateLimitBucket).where(
                AuthRateLimitBucket.bucket_key == bucket.bucket_key
            ).values(window_started_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        db.commit()
    finally:
        db.close()

    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401


def test_rate_limit_cleanup_deletes_only_old_rows_in_bounded_batches(client: TestClient) -> None:
    from datetime import timedelta, timezone

    from sqlalchemy import select, update

    from app.core.auth_rate_limit import cleanup_expired_auth_rate_limit_buckets
    from app.models.auth_rate_limit import AuthRateLimitBucket

    for email in ("old-one@example.com", "old-two@example.com", "old-three@example.com"):
        response = client.post(
            "/api/v1/auth/password-reset/request", json={"email": email}
        )
        assert response.status_code == 202

    db = TestingSessionLocal()
    try:
        old_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        db.execute(
            update(AuthRateLimitBucket).values(window_started_at=old_cutoff)
        )
        db.commit()
    finally:
        db.close()

    # This request creates a guaranteed fresh row after all older rows were aged.
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "fresh-after-aging@example.com"},
    )
    assert response.status_code == 202

    db = TestingSessionLocal()
    try:
        deleted = cleanup_expired_auth_rate_limit_buckets(
            db, older_than=datetime.now(timezone.utc) - timedelta(days=2), limit=1
        )
        assert deleted == 1
        remaining = db.scalars(select(AuthRateLimitBucket)).all()
        assert len(remaining) == 3
        assert any(
            row.window_started_at.replace(tzinfo=timezone.utc)
            > datetime.now(timezone.utc) - timedelta(days=1)
            for row in remaining
        )
    finally:
        db.close()



def test_email_verification_request_is_generic_and_sends_only_for_unverified(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth

    client.post(
        "/api/v1/auth/register",
        json={"email": "verify-me@example.com", "password": "StrongPass123!"},
    )
    delivered = {}

    def capture_delivery(recipient: str, raw_token: str) -> None:
        delivered.update(recipient=recipient, token=raw_token)

    monkeypatch.setattr(auth, "send_email_verification_email", capture_delivery)
    response = client.post(
        "/api/v1/auth/email-verification/request",
        json={"email": "VERIFY-ME@example.com"},
    )
    assert response.status_code == 202
    assert delivered["recipient"] == "verify-me@example.com"
    assert delivered["token"] not in response.text

    unknown = client.post(
        "/api/v1/auth/email-verification/request",
        json={"email": "unknown-verification@example.com"},
    )
    assert unknown.status_code == 202
    assert unknown.json() == response.json()


def test_email_verification_consumes_token_once_and_marks_user_verified(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth
    from app.models.email_verification import EmailVerificationToken
    from app.models.user import User

    client.post(
        "/api/v1/auth/register",
        json={"email": "verified@example.com", "password": "StrongPass123!"},
    )
    delivered = {}
    monkeypatch.setattr(
        auth,
        "send_email_verification_email",
        lambda recipient, raw_token: delivered.update(token=raw_token),
    )
    client.post(
        "/api/v1/auth/email-verification/request",
        json={"email": "verified@example.com"},
    )
    raw_token = delivered["token"]
    db = TestingSessionLocal()
    try:
        token_row = db.query(EmailVerificationToken).one()
        assert token_row.token_hash != raw_token
    finally:
        db.close()

    confirmed = client.post(
        "/api/v1/auth/email-verification/confirm",
        json={"token": raw_token},
    )
    assert confirmed.status_code == 200
    replay = client.post(
        "/api/v1/auth/email-verification/confirm",
        json={"token": raw_token},
    )
    assert replay.status_code == 400
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter_by(email="verified@example.com").one()
        assert user.email_verified is True
    finally:
        db.close()


def test_email_verification_delivery_failure_invalidates_token(
    client: TestClient, monkeypatch
) -> None:
    from app.api.v1 import auth

    client.post(
        "/api/v1/auth/register",
        json={"email": "verify-failure@example.com", "password": "StrongPass123!"},
    )
    captured = {}

    def fail_delivery(recipient, raw_token):
        captured["token"] = raw_token
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr(auth, "send_email_verification_email", fail_delivery)
    response = client.post(
        "/api/v1/auth/email-verification/request",
        json={"email": "verify-failure@example.com"},
    )
    assert response.status_code == 202
    rejected = client.post(
        "/api/v1/auth/email-verification/confirm",
        json={"token": captured["token"]},
    )
    assert rejected.status_code == 400


def test_login_can_require_verified_email_without_account_enumeration(
    client: TestClient, monkeypatch
) -> None:
    from types import SimpleNamespace

    from app.api.v1 import auth

    client.post(
        "/api/v1/auth/register",
        json={"email": "must-verify@example.com", "password": "StrongPass123!"},
    )
    monkeypatch.setattr(
        auth, "get_settings", lambda: SimpleNamespace(require_verified_email=True)
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "must-verify@example.com", "password": "StrongPass123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_unverified_account_session_is_blocked_when_policy_enabled(
    client: TestClient, monkeypatch
) -> None:
    from types import SimpleNamespace

    from app.api import dependencies

    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "protected-unverified@example.com", "password": "StrongPass123!"},
    )
    assert registration.status_code == 201
    token = registration.json()["access_token"]
    monkeypatch.setattr(
        dependencies, "get_settings", lambda: SimpleNamespace(require_verified_email=True)
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_email_verification_cleanup_removes_only_stale_rows_in_bounded_batches(
    client: TestClient,
) -> None:
    from datetime import timedelta, timezone

    from sqlalchemy import select
    from app.core.email_verification import cleanup_expired_email_verification_tokens
    from app.models.email_verification import EmailVerificationToken
    from app.models.user import User

    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "verify-cleanup@example.com", "password": "StrongPass123!"},
    )
    assert registration.status_code == 201
    db = TestingSessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "verify-cleanup@example.com"))
        assert user is not None
        now = datetime.now(timezone.utc)
        db.add_all([
            EmailVerificationToken(
                user_id=user.id, token_hash="a" * 64,
                expires_at=now - timedelta(days=4),
            ),
            EmailVerificationToken(
                user_id=user.id, token_hash="b" * 64,
                expires_at=now + timedelta(days=1),
                used_at=now - timedelta(days=3),
            ),
            EmailVerificationToken(
                user_id=user.id, token_hash="c" * 64,
                expires_at=now + timedelta(days=1),
            ),
        ])
        db.commit()
        deleted = cleanup_expired_email_verification_tokens(
            db, older_than=now - timedelta(hours=48), limit=1
        )
        assert deleted == 1
        remaining = db.scalars(select(EmailVerificationToken)).all()
        assert len(remaining) == 2
        assert any(row.token_hash == "c" * 64 for row in remaining)
    finally:
        db.close()


def test_patient_account_deletion_request_revokes_session_and_queues_work(client: TestClient) -> None:
    from sqlalchemy import select
    from app.models.account_deletion import AccountDeletionRequest
    from app.models.user import User

    registration = client.post("/api/v1/auth/register", json={
        "email": "delete-patient@example.com", "password": "StrongPass123!"
    })
    token = registration.json()["access_token"]
    response = client.post(
        "/api/v1/auth/me/deletion-request",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "StrongPass123!"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    db = TestingSessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "delete-patient@example.com"))
        request = db.scalar(select(AccountDeletionRequest))
        assert user is not None and user.is_active is False and user.token_version == 1
        assert request is not None and request.status == "pending"
    finally:
        db.close()


def test_account_deletion_requires_current_password_and_patient_role(client: TestClient) -> None:
    from app.models.user import User

    registration = client.post("/api/v1/auth/register", json={
        "email": "delete-guard@example.com", "password": "StrongPass123!"
    })
    token = registration.json()["access_token"]
    wrong = client.post(
        "/api/v1/auth/me/deletion-request",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "WrongPassword123!"},
    )
    assert wrong.status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter_by(email="delete-guard@example.com").one()
        user.role = "reviewer"
        db.commit()
    finally:
        db.close()
    forbidden = client.post(
        "/api/v1/auth/me/deletion-request",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "StrongPass123!"},
    )
    assert forbidden.status_code == 403


def test_account_deletion_worker_retries_image_storage_failure(client: TestClient, monkeypatch) -> None:
    from app.models.account_deletion import AccountDeletionRequest
    from app.models.prediction import Prediction, SkinImageAnalysis
    from app.models.user import User
    from app.workers import account_deletion

    registration = client.post("/api/v1/auth/register", json={
        "email": "delete-retry@example.com", "password": "StrongPass123!"
    })
    token = registration.json()["access_token"]
    client.post(
        "/api/v1/auth/me/deletion-request",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "StrongPass123!"},
    )
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter_by(email="delete-retry@example.com").one()
        prediction = Prediction(user_id=user.id, modality="skin_image", status="completed")
        db.add(prediction)
        db.flush()
        db.add(SkinImageAnalysis(
            prediction_id=prediction.id,
            object_key="skin-images/" + "c" * 32 + ".jpg",
            content_type="image/jpeg", image_sha256="d" * 64, storage_status="stored",
        ))
        db.commit()
        prediction_id = prediction.id
    finally:
        db.close()

    class FlakyStorage:
        def __init__(self):
            self.fail = True
            self.deleted = []
        def delete_private(self, key):
            if self.fail:
                raise OSError("storage unavailable")
            self.deleted.append(key)

    storage = FlakyStorage()
    monkeypatch.setattr(account_deletion, "build_skin_image_storage", lambda: storage)
    monkeypatch.setattr(account_deletion, "SessionLocal", TestingSessionLocal)
    first = account_deletion.run_deletion_batch()
    assert first == {"processed": 1, "completed": 0, "failed": 1}
    db = TestingSessionLocal()
    try:
        request = db.query(AccountDeletionRequest).one()
        image = db.query(SkinImageAnalysis).one()
        assert request.status == "pending"
        assert request.last_error_code == "private_image_deletion_failed"
        assert image.storage_status == "deletion_pending"
        assert db.get(Prediction, prediction_id) is not None
    finally:
        db.close()

    storage.fail = False
    second = account_deletion.run_deletion_batch()
    assert second == {"processed": 1, "completed": 1, "failed": 0}
    db = TestingSessionLocal()
    try:
        request = db.query(AccountDeletionRequest).one()
        user = db.query(User).filter(User.email.like("deleted+%@invalid.local")).one()
        assert request.status == "completed"
        assert user.display_name is None and user.is_active is False
        assert db.get(Prediction, prediction_id) is None
        assert storage.deleted == ["skin-images/" + "c" * 32 + ".jpg"]
    finally:
        db.close()


@pytest.mark.parametrize(
    ("existing_status", "expected_status", "expected_http_status"),
    [
        ("pending", "pending", 202),
        ("processing", "processing", 202),
        ("completed", None, 409),
        ("failed", None, 409),
    ],
)
def test_account_deletion_request_reports_existing_job_state(
    client: TestClient,
    existing_status: str,
    expected_status: str | None,
    expected_http_status: int,
) -> None:
    """Repeated deletion requests report in-flight state and never create duplicate jobs."""
    from sqlalchemy import select

    from app.models.account_deletion import AccountDeletionRequest
    from app.models.user import User

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"delete-existing-{existing_status}@example.com",
            "password": "StrongPass123!",
        },
    )
    assert registration.status_code == 201
    token = registration.json()["access_token"]
    db = TestingSessionLocal()
    try:
        user = db.scalar(
            select(User).where(
                User.email == f"delete-existing-{existing_status}@example.com"
            )
        )
        assert user is not None
        db.add(AccountDeletionRequest(user_id=user.id, status=existing_status))
        db.commit()
        user_id = user.id
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/me/deletion-request",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "StrongPass123!"},
    )
    assert response.status_code == expected_http_status

    db = TestingSessionLocal()
    try:
        jobs = db.scalars(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user_id
            )
        ).all()
        user = db.get(User, user_id)
        assert len(jobs) == 1
        assert user is not None and user.is_active is True
        if expected_status is not None:
            assert response.json()["status"] == expected_status
            assert isinstance(response.json()["message"], str)
        else:
            assert "detail" in response.json()
    finally:
        db.close()
