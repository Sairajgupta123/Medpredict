"""Tests for aggregate worker backlog signals and stable batch thresholds."""

from app.workers import account_deletion, auth_rate_limit_cleanup, email_verification_cleanup
from app.workers import skin_image_retention


def test_account_deletion_main_reports_lookahead_backlog(monkeypatch, capsys):
    monkeypatch.setattr(
        account_deletion,
        "run_deletion_batch",
        lambda *, limit: {
            "processed": limit,
            "completed": limit,
            "failed": 0,
            "possible_backlog": True,
        },
    )
    assert account_deletion.main() == 0
    output = capsys.readouterr().out
    assert f"processed={account_deletion.DELETION_BATCH_LIMIT}" in output
    assert "possible_backlog=true" in output


def test_retention_main_marks_full_batch_as_possible_backlog(monkeypatch, capsys):
    monkeypatch.setattr(
        skin_image_retention,
        "run_retention_batch",
        lambda *, limit: {"processed": limit, "deleted": limit, "failed": 0},
    )
    assert skin_image_retention.main() == 0
    output = capsys.readouterr().out
    assert "possible_backlog=true" in output


def test_retention_main_does_not_mark_short_batch_as_backlog(monkeypatch, capsys):
    monkeypatch.setattr(
        skin_image_retention,
        "run_retention_batch",
        lambda *, limit: {"processed": limit - 1, "deleted": limit - 1, "failed": 0},
    )
    assert skin_image_retention.main() == 0
    assert "possible_backlog=false" in capsys.readouterr().out


def test_auth_cleanup_main_marks_full_batch_as_possible_backlog(monkeypatch, capsys):
    monkeypatch.setattr(
        auth_rate_limit_cleanup,
        "run_cleanup_batch",
        lambda *, limit: limit,
    )
    assert auth_rate_limit_cleanup.main() == 0
    assert "possible_backlog=true" in capsys.readouterr().out


def test_auth_cleanup_main_does_not_mark_short_batch_as_backlog(monkeypatch, capsys):
    monkeypatch.setattr(
        auth_rate_limit_cleanup,
        "run_cleanup_batch",
        lambda *, limit: limit - 1,
    )
    assert auth_rate_limit_cleanup.main() == 0
    assert "possible_backlog=false" in capsys.readouterr().out


def test_email_cleanup_main_marks_full_batch_as_possible_backlog(monkeypatch, capsys):
    monkeypatch.setattr(
        email_verification_cleanup,
        "run_cleanup_batch",
        lambda *, limit: limit,
    )
    assert email_verification_cleanup.main() == 0
    assert "possible_backlog=true" in capsys.readouterr().out


def test_email_cleanup_main_does_not_mark_short_batch_as_backlog(monkeypatch, capsys):
    monkeypatch.setattr(
        email_verification_cleanup,
        "run_cleanup_batch",
        lambda *, limit: limit - 1,
    )
    assert email_verification_cleanup.main() == 0
    assert "possible_backlog=false" in capsys.readouterr().out
