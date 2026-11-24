"""Scheduled cleanup for expired email-verification tokens.

Run with: python -m app.workers.email_verification_cleanup
Schedule this command daily using the deployment platform's job scheduler.
"""

from datetime import datetime, timedelta, timezone

from app.core.email_verification import cleanup_expired_email_verification_tokens
from app.db.session import SessionLocal


def run_cleanup_batch(*, limit: int = 500) -> int:
    """Delete one bounded batch of tokens expired or consumed over 48h ago."""
    if not 1 <= limit <= 1000:
        raise ValueError("Cleanup batch limit must be between 1 and 1000.")
    db = SessionLocal()
    try:
        return cleanup_expired_email_verification_tokens(
            db,
            older_than=datetime.now(timezone.utc) - timedelta(hours=48),
            limit=limit,
        )
    finally:
        db.close()


def main() -> int:
    """Print aggregate-only cleanup status."""
    deleted = run_cleanup_batch()
    print(f"Email verification token cleanup: deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
