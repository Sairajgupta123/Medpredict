"""Tests that Alembic migration history matches the registered ORM schema."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.base import Base
from app import models  # noqa: F401 - register ORM metadata


BACKEND_DIR = Path(__file__).parents[1]


def test_initial_migration_files_exist() -> None:
    versions = BACKEND_DIR / "alembic" / "versions"
    assert (versions / "0001_initial_schema.py").is_file()
    assert (versions / "0002_reviewed_medical_knowledge.py").is_file()
    assert (versions / "0003_reviewed_symptom_catalog.py").is_file()


def test_migration_history_has_one_head_and_expected_parent_chain() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_revisions("heads")
    assert len(heads) == 1
    assert heads[0].revision == "0003_reviewed_symptom_catalog"
    assert heads[0].down_revision == "0002_reviewed_medical_knowledge"

    knowledge = script.get_revision("0002_reviewed_medical_knowledge")
    assert knowledge is not None
    assert knowledge.down_revision == "0001_initial_schema"

    initial = script.get_revision("0001_initial_schema")
    assert initial is not None
    assert initial.down_revision is None


def test_migration_sources_cover_registered_orm_tables() -> None:
    versions = BACKEND_DIR / "alembic" / "versions"
    migration_text = "\\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(versions.glob("*.py"))
    )

    for revision in (
        "0001_initial_schema",
        "0002_reviewed_medical_knowledge",
        "0003_reviewed_symptom_catalog",
    ):
        assert f'revision: str = "{revision}"' in migration_text
    for table_name in Base.metadata.tables:
        assert f'"{table_name}"' in migration_text
