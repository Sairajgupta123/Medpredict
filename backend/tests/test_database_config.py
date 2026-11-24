"""Tests for database configuration and session factory setup."""

from app.core.config import Settings
from app.db.base import Base
from app.db.session import SessionLocal, engine


def test_database_url_can_be_overridden() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    assert settings.database_url == "sqlite+pysqlite:///:memory:"


def test_sqlalchemy_base_is_available() -> None:
    assert hasattr(Base, "metadata")


def test_session_factory_is_bound_to_engine() -> None:
    assert SessionLocal.kw["bind"] is engine



def test_database_pool_settings_have_safe_defaults() -> None:
    settings = Settings()
    assert settings.database_pool_size == 5
    assert settings.database_max_overflow == 10
    assert settings.database_pool_timeout_seconds == 30
    assert settings.database_pool_recycle_seconds == 1800
    assert settings.database_connect_timeout_seconds == 5


def test_database_pool_settings_reject_unbounded_values() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(database_pool_size=0)
    with pytest.raises(ValidationError):
        Settings(database_max_overflow=101)
    with pytest.raises(ValidationError):
        Settings(database_pool_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(database_connect_timeout_seconds=31)
