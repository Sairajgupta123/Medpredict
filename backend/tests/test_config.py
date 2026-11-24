"""Runtime configuration security validation tests."""

import pytest

from app.core.config import Settings


def test_production_accepts_a_strong_application_secret() -> None:
    settings = Settings(
        environment="production",
        app_secret_key="a-cryptographically-random-secret-value",
        access_token_expire_minutes=30,
        require_verified_email=True,
        database_url="postgresql+psycopg://app:secret@db:5432/medipredict",
        frontend_base_url="https://app.example.test",
        cors_origins="https://app.example.test,https://www.example.test",
        smtp_host="smtp.example.test",
        smtp_sender_email="noreply@example.test",
        smtp_use_tls=True,
    )

    settings.validate_security_configuration()


@pytest.mark.parametrize(
    "secret",
    [
        "development-only-change-this-secret",
        "too-short",
    ],
)
def test_production_rejects_unsafe_application_secrets(secret: str) -> None:
    settings = Settings(
        environment="production",
        app_secret_key=secret,
        access_token_expire_minutes=30,
    )

    with pytest.raises(ValueError, match="APP_SECRET_KEY|development secret"):
        settings.validate_security_configuration()


@pytest.mark.parametrize("lifetime", [0, 1, 4])
def test_configuration_rejects_access_token_lifetime_below_five_minutes(
    lifetime: int,
) -> None:
    settings = Settings(
        environment="development",
        app_secret_key="local-test-secret",
        access_token_expire_minutes=lifetime,
    )

    with pytest.raises(ValueError, match="at least 5 minutes"):
        settings.validate_security_configuration()


def test_configuration_accepts_five_minute_minimum_token_lifetime() -> None:
    settings = Settings(
        environment="development",
        app_secret_key="local-test-secret",
        access_token_expire_minutes=5,
    )

    settings.validate_security_configuration()



@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"require_verified_email": False}, "REQUIRE_VERIFIED_EMAIL"),
        ({"database_url": "sqlite:///./medipredict.db"}, "PostgreSQL"),
        ({"frontend_base_url": "http://app.example.test"}, "FRONTEND_BASE_URL"),
        ({"cors_origins": "https://app.example.test,http://localhost:3000"}, "CORS_ORIGINS"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"smtp_host": None}, "SMTP_HOST"),
        ({"smtp_sender_email": None}, "SMTP_SENDER_EMAIL"),
        ({"smtp_use_tls": False}, "SMTP_USE_TLS"),
        ({"smtp_username": "mailer"}, "SMTP_USERNAME"),
    ],
)
def test_production_rejects_insecure_or_incomplete_deployment_settings(
    override: dict, message: str
) -> None:
    values = {
        "environment": "production",
        "app_secret_key": "a-cryptographically-random-secret-value",
        "access_token_expire_minutes": 30,
        "require_verified_email": True,
        "database_url": "postgresql+psycopg://app:secret@db:5432/medipredict",
        "frontend_base_url": "https://app.example.test",
        "cors_origins": "https://app.example.test",
        "smtp_host": "smtp.example.test",
        "smtp_sender_email": "noreply@example.test",
        "smtp_use_tls": True,
    }
    values.update(override)
    settings = Settings(**values)

    with pytest.raises(ValueError, match=message):
        settings.validate_security_configuration()
