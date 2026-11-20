"""Tests that the checked-in initial migration matches ORM table scope."""

from pathlib import Path

from app.db.base import Base
from app import models  # noqa: F401 - register ORM metadata


def test_initial_migration_file_exists() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0001_initial_schema.py"
    )
    assert migration.is_file()


def test_migration_revision_matches_initial_baseline() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0001_initial_schema.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0001_initial_schema"' in migration
    for table_name in Base.metadata.tables:
        assert f'"{table_name}"' in migration
