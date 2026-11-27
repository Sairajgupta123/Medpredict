"""SMTP delivery tests with a deterministic fake transport."""

from email import message_from_string
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core import email


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.credentials = None
        self.sent = []
        self.closed = False
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.credentials = (username, password)

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture(autouse=True)
def reset_smtp(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)


@pytest.fixture
def smtp_settings(monkeypatch):
    settings = SimpleNamespace(
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_sender_email="noreply@example.test",
        smtp_username="smtp-user",
        smtp_password="smtp-password",
        smtp_use_tls=True,
        frontend_base_url="https://app.example.test/",
    )
    monkeypatch.setattr(email, "get_settings", lambda: settings)
    return settings


@pytest.mark.parametrize(
    ("sender", "subject", "path", "token"),
    [
        (
            email.send_password_reset_email,
            "Reset your MediPredict password",
            "/reset-password",
            "reset-token+/=",
        ),
        (
            email.send_email_verification_email,
            "Verify your MediPredict email",
            "/verify-email",
            "verify-token+/=",
        ),
    ],
)
def test_account_emails_use_tls_auth_and_fragment_token(
    smtp_settings, sender, subject, path, token
):
    sender("person@example.test", token)

    assert len(FakeSMTP.instances) == 1
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == (
        "smtp.example.test",
        587,
        10,
    )
    assert smtp.started_tls is True
    assert smtp.credentials == ("smtp-user", "smtp-password")
    assert smtp.closed is True
    assert len(smtp.sent) == 1

    message = smtp.sent[0]
    assert message["To"] == "person@example.test"
    assert message["From"] == "noreply@example.test"
    assert message["Subject"] == subject
    body = message.get_content()
    link = next(part for part in body.split() if part.startswith("https://"))
    parsed = urlsplit(link)
    assert parsed.path == path
    assert parse_qs(parsed.fragment)["token"] == [token]
    assert parsed.query == ""


def test_smtp_without_credentials_does_not_attempt_login(
    smtp_settings,
):
    smtp_settings.smtp_username = None
    smtp_settings.smtp_password = None

    email.send_email_verification_email("person@example.test", "token")

    assert FakeSMTP.instances[0].started_tls is True
    assert FakeSMTP.instances[0].credentials is None


@pytest.mark.parametrize(
    "sender",
    [
        email.send_password_reset_email,
        email.send_email_verification_email,
    ],
)
def test_missing_smtp_configuration_fails_before_connecting(
    smtp_settings, sender
):
    smtp_settings.smtp_host = None

    with pytest.raises(RuntimeError, match="not configured"):
        sender("person@example.test", "token")

    assert FakeSMTP.instances == []


def test_smtp_delivery_error_is_propagated(smtp_settings, monkeypatch):
    class FailingSMTP(FakeSMTP):
        def send_message(self, message):
            raise OSError("smtp unavailable")

    monkeypatch.setattr(email.smtplib, "SMTP", FailingSMTP)

    with pytest.raises(OSError, match="smtp unavailable"):
        email.send_email_verification_email("person@example.test", "token")
