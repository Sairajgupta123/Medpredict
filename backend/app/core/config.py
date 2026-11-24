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
    smtp_port: int = 587
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
            if not self.database_url.lower().startswith(("postgresql://", "postgresql+")):
                raise ValueError("A PostgreSQL DATABASE_URL is required in production.")
            ssl_mode = parse_qs(urlsplit(self.database_url).query).get("sslmode", [""])[0].lower()
            if ssl_mode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("Production DATABASE_URL must require PostgreSQL TLS using sslmode=require, verify-ca, or verify-full.")
            if not self.frontend_base_url.lower().startswith("https://"):
                raise ValueError("FRONTEND_BASE_URL must use HTTPS in production.")
            origins = self.allowed_origins
            if not origins or any(
                not origin.lower().startswith("https://") or "*" in origin
                for origin in origins
            ):
                raise ValueError("Production CORS_ORIGINS must contain explicit HTTPS origins only.")
            if not self.smtp_host or not self.smtp_host.strip():
                raise ValueError("SMTP_HOST is required for production account verification.")
            if not self.smtp_sender_email or not self.smtp_sender_email.strip():
                raise ValueError("SMTP_SENDER_EMAIL is required for production account verification.")
            if not self.smtp_use_tls:
                raise ValueError("SMTP_USE_TLS must be enabled in production.")
            if bool(self.smtp_username) != bool(self.smtp_password):
                raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be configured together.")
        if self.access_token_expire_minutes < 5:
            raise ValueError("Access token lifetime must be at least 5 minutes.")


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    settings = Settings()
    settings.validate_security_configuration()
    return settings
