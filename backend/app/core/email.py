"""SMTP delivery for account recovery messages."""

import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

from app.core.config import get_settings


def send_password_reset_email(recipient: str, raw_token: str) -> None:
    """Send a reset link without logging or persisting the raw token."""
    settings = get_settings()
    required = (
        settings.smtp_host,
        settings.smtp_sender_email,
    )
    if not all(required):
        raise RuntimeError("Password reset email delivery is not configured.")

    query = urlencode({"token": raw_token})
    reset_url = (
        f"{settings.frontend_base_url.rstrip('/')}/reset-password?{query}"
    )
    message = EmailMessage()
    message["Subject"] = "Reset your MediPredict password"
    message["From"] = settings.smtp_sender_email
    message["To"] = recipient
    message.set_content(
        "A password reset was requested for your MediPredict account.\n\n"
        f"Use this link within 30 minutes: {reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def send_email_verification_email(recipient: str, raw_token: str) -> None:
    """Send a short-lived verification link without logging its token."""
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_sender_email:
        raise RuntimeError("Email verification delivery is not configured.")
    query = urlencode({"token": raw_token})
    verify_url = f"{settings.frontend_base_url.rstrip('/')}/verify-email#{query}"
    message = EmailMessage()
    message["Subject"] = "Verify your MediPredict email"
    message["From"] = settings.smtp_sender_email
    message["To"] = recipient
    message.set_content(
        "Please verify the email address associated with your MediPredict account.\n\n"
        f"Use this link within 30 minutes: {verify_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
