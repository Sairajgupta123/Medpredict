"""Retryable account erasure worker.

Run with: python -m app.workers.account_deletion
Schedule frequently (for example, every 15 minutes) while deletion requests exist.
"""
from datetime import datetime, timezone
import secrets
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.account_deletion import AccountDeletionRequest
from app.models.prediction import Prediction, SkinImageAnalysis
from app.models.user import User
from app.services.skin_image_storage_factory import build_skin_image_storage


def process_deletion_request(db, request_id: UUID, storage) -> bool:
    """Erase one patient account; retain only a non-identifying audit tombstone."""
    request = db.scalar(
        select(AccountDeletionRequest)
        .where(AccountDeletionRequest.id == request_id, AccountDeletionRequest.status == "pending")
        .with_for_update(skip_locked=True)
    )
    if request is None:
        return False
    user = db.scalar(select(User).where(User.id == request.user_id).with_for_update())
    if user is None or user.role != "patient" or user.is_active:
        request.last_error_code = "account_state_requires_manual_review"
        request.attempts += 1
        request.last_attempt_at = datetime.now(timezone.utc)
        db.commit()
        return False

    request.attempts += 1
    request.last_attempt_at = datetime.now(timezone.utc)
    db.commit()
    predictions = list(db.scalars(
        select(Prediction).where(Prediction.user_id == user.id).order_by(Prediction.id)
    ).all())
    prediction_ids = [item.id for item in predictions]
    images = []
    if prediction_ids:
        images = list(db.scalars(
            select(SkinImageAnalysis)
            .where(SkinImageAnalysis.prediction_id.in_(prediction_ids))
            .order_by(SkinImageAnalysis.id).with_for_update()
        ).all())

    for image in images:
        if image.storage_status == "deleted":
            continue
        if image.storage_status not in {"stored", "deletion_pending"}:
            request.last_error_code = "image_storage_state_requires_reconciliation"
            db.commit()
            return False
        image.storage_status = "deletion_pending"
        image.deletion_requested_at = image.deletion_requested_at or datetime.now(timezone.utc)
        db.commit()
        try:
            storage.delete_private(image.object_key)
        except Exception:
            request.last_error_code = "private_image_deletion_failed"
            db.commit()
            return False
        image.storage_status = "deleted"
        image.deleted_at = datetime.now(timezone.utc)
        db.commit()

    # Remove owned health rows only after all external image objects are confirmed gone.
    for prediction in predictions:
        db.delete(prediction)
    db.flush()

    # Immutable review/governance events use restrictive actor FKs. Retain this
    # user row as a non-login tombstone rather than breaking attribution history.
    user.email = f"deleted+{user.id.hex}@invalid.local"
    user.display_name = None
    user.password_hash = hash_password(secrets.token_urlsafe(48))
    user.is_active = False
    user.email_verified = False
    user.token_version += 1
    request.status = "completed"
    request.last_error_code = None
    request.completed_at = datetime.now(timezone.utc)
    db.commit()
    return True


def run_deletion_batch(*, limit: int = 25) -> dict[str, int]:
    """Process a bounded batch and expose aggregate counts only."""
    if not 1 <= limit <= 100:
        raise ValueError("Deletion batch limit must be between 1 and 100.")
    storage = build_skin_image_storage()
    db = SessionLocal()
    try:
        request_ids = list(db.scalars(
            select(AccountDeletionRequest.id)
            .where(AccountDeletionRequest.status == "pending")
            .order_by(AccountDeletionRequest.requested_at, AccountDeletionRequest.id)
            .limit(limit)
        ).all())
        summary = {"processed": 0, "completed": 0, "failed": 0}
        for request_id in request_ids:
            summary["processed"] += 1
            try:
                if process_deletion_request(db, request_id, storage):
                    summary["completed"] += 1
                else:
                    summary["failed"] += 1
            except Exception:
                db.rollback()
                row = db.get(AccountDeletionRequest, request_id)
                if row is not None and row.status == "pending":
                    row.attempts += 1
                    row.last_attempt_at = datetime.now(timezone.utc)
                    row.last_error_code = "unexpected_processing_error"
                    db.commit()
                summary["failed"] += 1
        return summary
    finally:
        db.close()


def main() -> int:
    """Print aggregate-only status and fail when requests need retry."""
    summary = run_deletion_batch()
    print(
        "Account deletion batch: "
        f"processed={summary['processed']} completed={summary['completed']} failed={summary['failed']}"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
