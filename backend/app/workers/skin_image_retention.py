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


if __name__ == "__main__":
    summary = run_retention_batch()
    print(
        "Skin-image retention batch: "
        f"processed={summary['processed']} "
        f"deleted={summary['deleted']} "
        f"failed={summary['failed']}"
    )
