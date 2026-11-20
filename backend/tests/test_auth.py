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
    token = jwt.encode(payload, "not-the-application-secret", algorithm="HS256")

    assert decode_access_token(token) is None


def test_non_access_jwt_type_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(type="refresh")

    assert decode_access_token(token) is None


def test_token_from_untrusted_issuer_is_rejected() -> None:
    from app.core.security import decode_access_token

    token = _signed_test_token(iss="untrusted-service")

    assert decode_access_token(token) is None


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

