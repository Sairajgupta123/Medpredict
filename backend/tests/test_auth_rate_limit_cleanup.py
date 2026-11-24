"""Operational tests for authentication rate-limit cleanup."""

import pytest

from app.workers import auth_rate_limit_cleanup as worker


@pytest.mark.parametrize("limit", [0, -1, 1001])
def test_cleanup_worker_rejects_unbounded_batch_sizes(monkeypatch, limit):
    monkeypatch.setattr(
        worker,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("session must not be opened")),
    )
    with pytest.raises(ValueError, match="between 1 and 1000"):
        worker.run_cleanup_batch(limit=limit)


def test_cleanup_worker_passes_48_hour_cutoff_and_closes_session(monkeypatch):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    db = FakeSession()
    captured = {}
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)

    def fake_cleanup(session, *, older_than, limit):
        captured.update(session=session, older_than=older_than, limit=limit)
        return 12

    monkeypatch.setattr(worker, "cleanup_expired_auth_rate_limit_buckets", fake_cleanup)
    assert worker.run_cleanup_batch(limit=25) == 12
    assert captured["session"] is db
    assert captured["limit"] == 25
    assert captured["older_than"].tzinfo is not None
    assert db.closed is True


def test_cleanup_worker_closes_session_when_cleanup_raises(monkeypatch):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    db = FakeSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        worker,
        "cleanup_expired_auth_rate_limit_buckets",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )
    with pytest.raises(RuntimeError, match="cleanup failed"):
        worker.run_cleanup_batch()
    assert db.closed is True


def test_cleanup_worker_prints_only_aggregate_count(monkeypatch, capsys):
    monkeypatch.setattr(worker, "run_cleanup_batch", lambda: 7)
    assert worker.main() == 0
    output = capsys.readouterr().out
    assert "deleted=7" in output
    assert "example.com" not in output


def test_cleanup_index_supports_expiry_scan():
    from app.models.auth_rate_limit import AuthRateLimitBucket

    indexes = {index.name for index in AuthRateLimitBucket.__table__.indexes}
    assert "ix_auth_rate_limit_buckets_window_started_at" in indexes
