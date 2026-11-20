"""Centralized application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the MediPredict API."""

    app_name: str = "MediPredict API"
    app_version: str = "0.1.0"
    environment: str = "development"
    app_secret_key: str = "development-only-change-this-secret"
    cors_origins: str = "http://localhost:3000"
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


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
