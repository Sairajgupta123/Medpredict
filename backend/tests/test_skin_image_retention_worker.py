"""Operational tests for the scheduled skin-image retention worker."""

import pytest

from app.services.skin_image_storage import DisabledSkinImageStorage
from app.workers import skin_image_retention as worker


def test_retention_worker_fails_closed_when_storage_is_disabled(monkeypatch):
    monkeypatch.setattr(worker, "build_skin_image_storage", lambda: DisabledSkinImageStorage())
    with pytest.raises(RuntimeError, match="storage is not configured"):
        worker.run_retention_batch()


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_retention_worker_rejects_unbounded_batch_sizes(monkeypatch, limit):
    def unexpected_storage():
        raise AssertionError("storage must not be initialized for an invalid batch size")

    monkeypatch.setattr(worker, "build_skin_image_storage", unexpected_storage)
    with pytest.raises(ValueError, match="between 1 and 500"):
        worker.run_retention_batch(limit=limit)


def test_retention_worker_returns_success_exit_code_for_clean_batch(monkeypatch, capsys):
    monkeypatch.setattr(
        worker,
        "run_retention_batch",
        lambda: {"processed": 4, "deleted": 4, "failed": 0},
    )
    assert worker.main() == 0
    output = capsys.readouterr().out
    assert "processed=4 deleted=4 failed=0" in output
    assert "skin-images/" not in output


def test_retention_worker_returns_failure_exit_code_when_cleanup_needs_retry(monkeypatch, capsys):
    monkeypatch.setattr(
        worker,
        "run_retention_batch",
        lambda: {"processed": 3, "deleted": 2, "failed": 1},
    )
    assert worker.main() == 1
    output = capsys.readouterr().out
    assert "processed=3 deleted=2 failed=1" in output
    assert "skin-images/" not in output
