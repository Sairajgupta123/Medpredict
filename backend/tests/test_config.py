"""Runtime configuration security validation tests."""

import pytest

from app.core.config import Settings


def test_production_accepts_a_strong_application_secret() -> None:
    settings = Settings(
        environment="production",
        app_secret_key="a-cryptographically-random-secret-value",
        access_token_expire_minutes=30,
        require_verified_email=True,
        database_url="postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=require",
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
        ({"database_url": "postgresql+psycopg://app:secret@db:5432/medipredict"}, "sslmode"),
        ({"database_url": "postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=disable"}, "sslmode"),
        ({"frontend_base_url": "http://app.example.test"}, "FRONTEND_BASE_URL"),
        ({"cors_origins": "https://app.example.test,http://localhost:3000"}, "CORS_ORIGINS"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://app.example.test/admin"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://user:pass@app.example.test"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://app.example.test?mode=unsafe"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://app.example.test:invalid"}, "CORS_ORIGINS"),
        ({"frontend_base_url": "https://"}, "FRONTEND_BASE_URL"),
        ({"frontend_base_url": "https://user:pass@app.example.test"}, "FRONTEND_BASE_URL"),
        ({"frontend_base_url": "https://app.example.test#fragment"}, "FRONTEND_BASE_URL"),
        ({"database_url": "postgresql+psycopg:///medipredict?sslmode=require"}, "PostgreSQL"),
        ({"database_url": "postgresql+psycopg://app:secret@/medipredict?sslmode=require"}, "PostgreSQL"),
        ({"database_url": "postgresql+psycopg://app:secret@db:invalid/medipredict?sslmode=require"}, "PostgreSQL"),
        ({"database_url": "postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=require#fragment"}, "PostgreSQL"),
        ({"smtp_host": None}, "SMTP_HOST"),
        ({"smtp_sender_email": None}, "SMTP_SENDER_EMAIL"),
        ({"smtp_use_tls": False}, "SMTP_USE_TLS"),
        ({"smtp_username": "mailer"}, "SMTP_USERNAME"),
        ({"smtp_password": "secret"}, "SMTP_USERNAME and SMTP_PASSWORD"),
        ({"smtp_host": "   "}, "SMTP_HOST"),
        ({"smtp_sender_email": "   "}, "SMTP_SENDER_EMAIL"),
        ({"skin_image_s3_bucket": "private-images"}, "SKIN_IMAGE_S3_BUCKET and SKIN_IMAGE_S3_REGION"),
        ({"skin_image_s3_region": "ap-south-1"}, "SKIN_IMAGE_S3_BUCKET and SKIN_IMAGE_S3_REGION"),
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
        "database_url": "postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=require",
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


def test_production_rejects_private_image_storage_without_retention_policy() -> None:
    settings = Settings(
        environment="production",
        app_secret_key="a-cryptographically-random-secret-value",
        require_verified_email=True,
        database_url="postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=require",
        frontend_base_url="https://app.example.test",
        cors_origins="https://app.example.test",
        smtp_host="smtp.example.test",
        smtp_sender_email="noreply@example.test",
        skin_image_s3_bucket="private-medipredict-images",
        skin_image_s3_region="ap-south-1",
    )

    with pytest.raises(ValueError, match="SKIN_IMAGE_RETENTION_DAYS"):
        settings.validate_security_configuration()


def test_private_image_storage_accepts_bounded_explicit_retention_policy() -> None:
    settings = Settings(
        environment="production",
        app_secret_key="a-cryptographically-random-secret-value",
        require_verified_email=True,
        database_url="postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=require",
        frontend_base_url="https://app.example.test",
        cors_origins="https://app.example.test",
        smtp_host="smtp.example.test",
        smtp_sender_email="noreply@example.test",
        skin_image_s3_bucket="private-medipredict-images",
        skin_image_s3_region="ap-south-1",
        skin_image_retention_days=30,
    )

    settings.validate_security_configuration()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"skin_image_s3_encryption": "none"}, "SKIN_IMAGE_S3_ENCRYPTION"),
        ({"skin_image_s3_encryption": "aws:kms"}, "SKIN_IMAGE_S3_KMS_KEY_ID"),
        (
            {
                "skin_image_s3_encryption": "AES256",
                "skin_image_s3_kms_key_id": "alias/medipredict",
            },
            "must not be set with AES256",
        ),
        (
            {"skin_image_s3_endpoint_url": "http://storage.example.test"},
            "SKIN_IMAGE_S3_ENDPOINT_URL",
        ),
    ],
)
def test_production_rejects_unsafe_private_s3_settings(
    override: dict, message: str
) -> None:
    values = {
        "environment": "production",
        "app_secret_key": "a-cryptographically-random-secret-value",
        "require_verified_email": True,
        "database_url": "postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=require",
        "frontend_base_url": "https://app.example.test",
        "cors_origins": "https://app.example.test",
        "smtp_host": "smtp.example.test",
        "smtp_sender_email": "noreply@example.test",
        "skin_image_s3_bucket": "private-medipredict-images",
        "skin_image_s3_region": "ap-south-1",
        "skin_image_retention_days": 30,
    }
    values.update(override)
    settings = Settings(**values)

    with pytest.raises(ValueError, match=message):
        settings.validate_security_configuration()


def test_production_accepts_private_s3_kms_configuration() -> None:
    settings = Settings(
        environment="production",
        app_secret_key="a-cryptographically-random-secret-value",
        require_verified_email=True,
        database_url="postgresql+psycopg://app:secret@db:5432/medipredict?sslmode=require",
        frontend_base_url="https://app.example.test",
        cors_origins="https://app.example.test",
        smtp_host="smtp.example.test",
        smtp_sender_email="noreply@example.test",
        skin_image_s3_bucket="private-medipredict-images",
        skin_image_s3_region="ap-south-1",
        skin_image_s3_encryption="aws:kms",
        skin_image_s3_kms_key_id="alias/medipredict-images",
        skin_image_retention_days=30,
    )

    settings.validate_security_configuration()


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_configuration_rejects_invalid_smtp_ports(port: int) -> None:
    with pytest.raises(ValueError):
        Settings(smtp_port=port)


@pytest.mark.parametrize("port", [25, 587, 2525, 65535])
def test_configuration_accepts_valid_smtp_port_range(port: int) -> None:
    settings = Settings(smtp_port=port)
    assert settings.smtp_port == port
