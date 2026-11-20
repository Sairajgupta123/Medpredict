"""Tests that the checked-in initial migration matches ORM table scope."""

from pathlib import Path

from app.db.base import Base
from app import models  # noqa: F401 - register ORM metadata


def test_initial_migration_file_exists() -> None:
    versions = Path(__file__).parents[1] / "alembic" / "versions"
    assert (versions / "0001_initial_schema.py").is_file()
    assert (versions / "0002_reviewed_medical_knowledge.py").is_file()


def test_migration_revision_matches_initial_baseline() -> None:
    versions = Path(__file__).parents[1] / "alembic" / "versions"
    migration_text = "\\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(versions.glob("*.py"))
    )
    assert 'revision: str = "0001_initial_schema"' in migration_text
    assert 'revision: str = "0002_reviewed_medical_knowledge"' in migration_text
    for table_name in Base.metadata.tables:
        assert f'"{table_name}"' in migration_text
