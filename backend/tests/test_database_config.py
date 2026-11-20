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
