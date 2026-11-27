"""Scheduled private skin-image retention cleanup entry point.

Run with: python -m app.workers.skin_image_retention
Schedule this command using the deployment platform's cron/job scheduler.
"""

from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.services.prediction_history import purge_expired_skin_image_records
from app.services.skin_image_storage import DisabledSkinImageStorage
from app.services.skin_image_storage_factory import build_skin_image_storage


def run_retention_batch(*, limit: int = 100) -> dict[str, int]:
    """Execute one bounded retention batch without logging image identifiers."""
    if not 1 <= limit <= 500:
        raise ValueError("Retention batch limit must be between 1 and 500.")

    storage = build_skin_image_storage()
    if isinstance(storage, DisabledSkinImageStorage):
        raise RuntimeError(
            "Private image storage is not configured; retention cleanup is disabled."
        )
    db = SessionLocal()
    try:
        return purge_expired_skin_image_records(
            db,
            image_storage=storage,
            as_of=datetime.now(timezone.utc),
            limit=limit,
        )
    finally:
        db.close()


def main() -> int:
    """Print aggregate-only status and return non-zero when any deletion failed."""
    summary = run_retention_batch()
    print(
        "Skin-image retention batch: "
        f"processed={summary['processed']} "
        f"deleted={summary['deleted']} "
        f"failed={summary['failed']} "
        f"possible_backlog={str(summary['processed'] >= 100).lower()}"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
