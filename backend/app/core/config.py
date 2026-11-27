"""Centralized application settings loaded from environment variables."""

from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the MediPredict API."""

    app_name: str = "MediPredict API"
    app_version: str = "0.1.0"
    environment: str = "development"
    app_secret_key: str = "development-only-change-this-secret"
    access_token_expire_minutes: int = 30
    require_verified_email: bool = False
    cors_origins: str = "http://localhost:3000"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_sender_email: str | None = None
    smtp_use_tls: bool = True
    frontend_base_url: str = "http://localhost:3000"
    skin_image_s3_bucket: str | None = None
    skin_image_s3_region: str | None = None
    skin_image_s3_endpoint_url: str | None = None
    skin_image_s3_encryption: str = "AES256"
    skin_image_s3_kms_key_id: str | None = None
    skin_image_retention_days: int | None = Field(default=None, ge=1, le=3650)
    skin_research_checkpoint_path: str | None = None
    text_research_artifact_path: str | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=120)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_url: str = (
        "postgresql+psycopg://medipredict:change-me@localhost:5432/medipredict"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        """Return configured CORS origins as a clean list."""
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @staticmethod
    def _is_https_url(value: str, *, origin_only: bool = False) -> bool:
        """Validate an absolute HTTPS URL without credentials or malformed authority."""
        try:
            parsed = urlsplit(value)
            _ = parsed.port  # Force validation of malformed port values.
        except ValueError:
            return False
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            return False
        if origin_only and (parsed.path not in {"", "/"} or parsed.query):
            return False
        return True

    def validate_security_configuration(self) -> None:
        """Reject unsafe secret configuration in production."""
        if self.environment.lower() == "production":
            if len(self.app_secret_key) < 32:
                raise ValueError(
                    "APP_SECRET_KEY must contain at least 32 characters in production."
                )
            if self.app_secret_key == "development-only-change-this-secret":
                raise ValueError("The development secret cannot be used in production.")
            if not self.require_verified_email:
                raise ValueError("REQUIRE_VERIFIED_EMAIL must be enabled in production.")
            try:
                database = urlsplit(self.database_url)
                _ = database.port
            except ValueError:
                database = None
            if (
                database is None
                or database.scheme.lower() != "postgresql"
                and not database.scheme.lower().startswith("postgresql+")
                or not database.hostname
                or not database.username
                or database.fragment
            ):
                raise ValueError("A valid PostgreSQL DATABASE_URL with a host and username is required in production.")
            ssl_mode = parse_qs(database.query).get("sslmode", [""])[0].lower()
            if ssl_mode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("Production DATABASE_URL must require PostgreSQL TLS using sslmode=require, verify-ca, or verify-full.")
            if not self._is_https_url(self.frontend_base_url):
                raise ValueError("FRONTEND_BASE_URL must be a valid absolute HTTPS URL in production.")
            origins = self.allowed_origins
            if not origins or any(
                "*" in origin or not self._is_https_url(origin, origin_only=True)
                for origin in origins
            ):
                raise ValueError("Production CORS_ORIGINS must contain valid HTTPS origins only (scheme and host, without path, query, credentials or wildcard).")
            if not self.smtp_host or not self.smtp_host.strip():
                raise ValueError("SMTP_HOST is required for production account verification.")
            if not self.smtp_sender_email or not self.smtp_sender_email.strip():
                raise ValueError("SMTP_SENDER_EMAIL is required for production account verification.")
            if not self.smtp_use_tls:
                raise ValueError("SMTP_USE_TLS must be enabled in production.")
            if bool(self.smtp_username) != bool(self.smtp_password):
                raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be configured together.")
            if bool(self.skin_image_s3_bucket and self.skin_image_s3_bucket.strip()) != bool(
                self.skin_image_s3_region and self.skin_image_s3_region.strip()
            ):
                raise ValueError(
                    "SKIN_IMAGE_S3_BUCKET and SKIN_IMAGE_S3_REGION must be configured together."
                )
            image_storage_enabled = bool(
                self.skin_image_s3_bucket and self.skin_image_s3_bucket.strip()
            )
            if image_storage_enabled:
                if self.skin_image_retention_days is None:
                    raise ValueError("SKIN_IMAGE_RETENTION_DAYS is required when private skin-image storage is enabled.")
                if self.skin_image_s3_encryption not in {"AES256", "aws:kms"}:
                    raise ValueError("SKIN_IMAGE_S3_ENCRYPTION must be AES256 or aws:kms.")
                if self.skin_image_s3_encryption == "aws:kms" and not (
                    self.skin_image_s3_kms_key_id
                    and self.skin_image_s3_kms_key_id.strip()
                ):
                    raise ValueError("SKIN_IMAGE_S3_KMS_KEY_ID is required when using aws:kms.")
                if self.skin_image_s3_encryption == "AES256" and self.skin_image_s3_kms_key_id:
                    raise ValueError("SKIN_IMAGE_S3_KMS_KEY_ID must not be set with AES256 encryption.")
                if self.skin_image_s3_endpoint_url and not self._is_https_url(
                    self.skin_image_s3_endpoint_url
                ):
                    raise ValueError("SKIN_IMAGE_S3_ENDPOINT_URL must be a valid absolute HTTPS URL.")
        if self.access_token_expire_minutes < 5:
            raise ValueError("Access token lifetime must be at least 5 minutes.")


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    settings = Settings()
    settings.validate_security_configuration()
    return settings
