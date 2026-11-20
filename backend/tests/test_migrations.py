"""Tests that Alembic migration history matches the registered ORM schema."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app import models  # noqa: F401 - register ORM metadata
from app.db.base import Base


BACKEND_DIR = Path(__file__).parents[1]


def test_migration_files_exist() -> None:
    versions = BACKEND_DIR / "alembic" / "versions"
    for name in (
        "0001_initial_schema.py",
        "0002_reviewed_medical_knowledge.py",
        "0003_reviewed_symptom_catalog.py",
        "0004_prediction_history_consent.py",
        "0004_knowledge_review_due_dates.py",
        "0005_merge_knowledge_and_consent_heads.py",
        "0006_disease_catalog_review.py",
        "0007_disease_symptom_link_review.py",
        "0008_catalog_reviewer_roles.py",
        "0009_catalog_review_audit.py",
        "0010_role_provisioning_audit.py",
        "0011_catalog_audit_constraints.py",
        "0012_reviewer_scopes.py",
        "0013_catalog_references.py",
    ):
        assert (versions / name).is_file()


def test_migration_history_has_one_head_and_expected_parent_chain() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_revisions("heads")
    assert len(heads) == 1
    assert heads[0].revision == "0013_catalog_references"
    assert heads[0].down_revision == "0012_reviewer_scopes"

    merge = script.get_revision("0005_merge_knowledge_consent")
    assert merge is not None
    assert set(merge.down_revision) == {
        "0004_knowledge_review_due_dates",
        "0004_prediction_history_consent",
    }

    expected = {
        "0004_knowledge_review_due_dates": "0003_reviewed_symptom_catalog",
        "0004_prediction_history_consent": "0003_reviewed_symptom_catalog",
        "0003_reviewed_symptom_catalog": "0002_reviewed_medical_knowledge",
        "0002_reviewed_medical_knowledge": "0001_initial_schema",
        "0001_initial_schema": None,
    }
    for revision, parent in expected.items():
        current = script.get_revision(revision)
        assert current is not None
        assert current.down_revision == parent


def test_migration_sources_cover_registered_orm_tables() -> None:
    versions = BACKEND_DIR / "alembic" / "versions"
    migration_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(versions.glob("*.py"))
    )

    for revision in (
        "0001_initial_schema",
        "0002_reviewed_medical_knowledge",
        "0003_reviewed_symptom_catalog",
        "0004_prediction_history_consent",
        "0004_knowledge_review_due_dates",
        "0005_merge_knowledge_consent",
        "0006_disease_catalog_review",
        "0007_disease_symptom_link_review",
        "0008_catalog_reviewer_roles",
        "0009_catalog_review_audit",
        "0010_role_provisioning_audit",
        "0011_catalog_audit_constraints",
        "0012_reviewer_scopes",
        "0013_catalog_references",
    ):
        assert f'revision: str = "{revision}"' in migration_text
    for table_name in Base.metadata.tables:
        assert f'"{table_name}"' in migration_text
