"""Runtime configuration security validation tests."""

import pytest

from app.core.config import Settings


def test_production_accepts_a_strong_application_secret() -> None:
    settings = Settings(
        environment="production",
        app_secret_key="a-cryptographically-random-secret-value",
        access_token_expire_minutes=30,
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
