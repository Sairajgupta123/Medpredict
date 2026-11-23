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

def test_retention_worker_passes_bounded_batch_and_closes_session(monkeypatch):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    db = FakeSession()
    storage = object()
    captured = {}

    monkeypatch.setattr(worker, "build_skin_image_storage", lambda: storage)
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)

    def fake_purge(session, *, image_storage, as_of, limit):
        captured.update(
            session=session, image_storage=image_storage, as_of=as_of, limit=limit
        )
        return {"processed": 2, "deleted": 2, "failed": 0}

    monkeypatch.setattr(worker, "purge_expired_skin_image_records", fake_purge)

    assert worker.run_retention_batch(limit=25) == {
        "processed": 2, "deleted": 2, "failed": 0
    }
    assert captured["session"] is db
    assert captured["image_storage"] is storage
    assert captured["limit"] == 25
    assert captured["as_of"].tzinfo is not None
    assert captured["as_of"].utcoffset().total_seconds() == 0
    assert db.closed is True


def test_retention_worker_closes_session_when_purge_raises(monkeypatch):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    db = FakeSession()
    monkeypatch.setattr(worker, "build_skin_image_storage", lambda: object())
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)

    def fail_purge(*args, **kwargs):
        raise RuntimeError("database operation failed")

    monkeypatch.setattr(worker, "purge_expired_skin_image_records", fail_purge)
    with pytest.raises(RuntimeError, match="database operation failed"):
        worker.run_retention_batch()
    assert db.closed is True
