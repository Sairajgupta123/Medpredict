"""Retryable account erasure worker.

Run with: python -m app.workers.account_deletion
Schedule frequently (for example, every 15 minutes) while deletion requests exist.
"""
from datetime import datetime, timedelta, timezone
import secrets
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, or_, select, update

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.account_deletion import AccountDeletionRequest
from app.models.email_verification import EmailVerificationToken
from app.models.password_reset import PasswordResetToken
from app.models.prediction import (
    Prediction,
    SkinImageAnalysis,
    SkinImageReviewEvent,
)
from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
from app.models.user import User
from app.services.skin_image_storage_factory import build_skin_image_storage


def _release_for_retry(request: AccountDeletionRequest, error_code: str) -> None:
    """Make a claimed request available for a later retry."""
    request.status = "pending"
    request.claim_token = None
    request.last_error_code = error_code


class DeletionClaimLost(RuntimeError):
    """Raised when another worker has taken ownership of a deletion job."""


def _claim_deletion_request(db, request_id: UUID, *, now: datetime, stale_before: datetime) -> UUID | None:
    """Claim one pending or abandoned job with a unique fencing token."""
    claim_token = uuid4()
    claimed_id = db.scalar(
        update(AccountDeletionRequest)
        .where(
            AccountDeletionRequest.id == request_id,
            or_(
                AccountDeletionRequest.status == "pending",
                and_(
                    AccountDeletionRequest.status == "processing",
                    or_(
                        AccountDeletionRequest.last_attempt_at < stale_before,
                        AccountDeletionRequest.last_attempt_at.is_(None),
                    ),
                ),
            ),
        )
         .values(
            status="processing",
            claim_token=claim_token,
            attempts=AccountDeletionRequest.attempts + 1,
            last_attempt_at=now,
        )
        .returning(AccountDeletionRequest.id)
    )
    db.commit()
    return claim_token if claimed_id is not None else None


def _lock_owned_request(db, request_id: UUID, claim_token: UUID | None):
    """Lock the job row and fence out workers whose claim has expired."""
    request = db.scalar(
        select(AccountDeletionRequest)
        .where(
            AccountDeletionRequest.id == request_id,
            AccountDeletionRequest.status == "processing",
        )
        .with_for_update(skip_locked=True)
    )
    if request is None:
        return None
    if claim_token is not None and request.claim_token != claim_token:
        raise DeletionClaimLost("Deletion job claim was replaced by another worker.")
    return request


def process_deletion_request(db, request_id: UUID, storage, *, claim_token: UUID | None = None) -> bool:
    """Erase one claimed patient account; retain a non-identifying audit tombstone."""
    request = _lock_owned_request(db, request_id, claim_token)
    if request is None:
        return False

    user = db.scalar(select(User).where(User.id == request.user_id).with_for_update())
    if user is None or user.role != "patient" or user.is_active:
        request.status = "failed"
        request.claim_token = None
        request.last_error_code = "account_state_requires_manual_review"
        db.commit()
        return False

    # Remove outstanding recovery/verification credentials as soon as erasure
    # starts; they are not governance records and must not survive as user data.
    db.execute(
        delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    db.execute(
        delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
    )
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

    # Revoke exact image-review scopes before attempting external object deletion.
    # This closes reviewer access immediately, including when storage is unavailable.
    image_scope_keys = {str(image.prediction_id) for image in images}
    access_changed = False
    # Clear every assignment on owned images, even if its original scope was
    # already revoked or is missing due to legacy data.
    for image in images:
        if image.assigned_reviewer_id is None:
            continue
        previous_reviewer_id = image.assigned_reviewer_id
        image.assigned_reviewer_id = None
        image.assigned_by = None
        image.assigned_at = None
        image.review_status = "pending"
        db.add(SkinImageReviewEvent(
            prediction_id=image.prediction_id,
            image_analysis_id=image.id,
            event_type="unassigned",
            actor_id=user.id,
            assigned_reviewer_id=previous_reviewer_id,
            reason="Assignment cleared because the owner requested account deletion.",
        ))
        access_changed = True

    if image_scope_keys:
        scopes = list(db.scalars(
            select(CatalogReviewerScope)
            .where(
                CatalogReviewerScope.scope_type == "skin_image",
                CatalogReviewerScope.scope_key.in_(image_scope_keys),
                CatalogReviewerScope.revoked_at.is_(None),
            )
            .order_by(CatalogReviewerScope.id)
            .with_for_update()
        ).all())
        for scope in scopes:
            scope.revoked_by = user.id
            scope.revoked_at = datetime.now(timezone.utc)
            scope.revoke_reason = "Owner requested account deletion."
            db.add(CatalogReviewerScopeEvent(
                scope_id=scope.id,
                reviewer_id=scope.reviewer_id,
                event_type="revoked",
                scope_type=scope.scope_type,
                scope_key=scope.scope_key,
                operator_id=user.id,
                reason="Owner requested account deletion.",
            ))
            access_changed = True
    if access_changed:
        # The scope/assignment cleanup can be lengthy; fence its commit too.
        request = _lock_owned_request(db, request_id, claim_token)
        if request is None:
            return False
        db.commit()

    for image in images:
        request = _lock_owned_request(db, request_id, claim_token)
        if request is None:
            return False
        if image.storage_status == "deleted":
            continue
        if image.storage_status not in {"stored", "deletion_pending"}:
            _release_for_retry(request, "image_storage_state_requires_reconciliation")
            db.commit()
            return False
        image.storage_status = "deletion_pending"
        # Refresh the shared deletion lease so retention cannot reclaim this image
        # while account erasure is performing its external storage operation.
        image.deletion_requested_at = datetime.now(timezone.utc)
        db.commit()
        try:
            storage.delete_private(image.object_key)
        except Exception:
            request = _lock_owned_request(db, request_id, claim_token)
            if request is None:
                return False
            _release_for_retry(request, "private_image_deletion_failed")
            db.commit()
            return False
        # Re-check ownership after the external call: a stale worker must not
        # commit database erasure after a replacement worker has claimed the job.
        request = _lock_owned_request(db, request_id, claim_token)
        if request is None:
            return False
        image.storage_status = "deleted"
        image.deleted_at = datetime.now(timezone.utc)
        db.commit()

    # Fence the final relational deletion and tombstone transaction as well.
    request = _lock_owned_request(db, request_id, claim_token)
    if request is None:
        return False

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
    user.last_login_at = None
    user.token_version += 1
    request.status = "completed"
    request.last_error_code = None
    request.completed_at = datetime.now(timezone.utc)
    request.claim_token = None
    db.commit()
    return True


def run_deletion_batch(*, limit: int = 25) -> dict[str, int]:
    """Atomically claim a bounded batch and expose aggregate counts only."""
    if not 1 <= limit <= 100:
        raise ValueError("Deletion batch limit must be between 1 and 100.")
    storage = build_skin_image_storage()
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        stale_processing_before = now - timedelta(hours=2)
        candidate_ids = list(db.scalars(
            select(AccountDeletionRequest.id)
            .where(or_(
                AccountDeletionRequest.status == "pending",
                and_(
                    AccountDeletionRequest.status == "processing",
                    or_(
                        AccountDeletionRequest.last_attempt_at < stale_processing_before,
                        AccountDeletionRequest.last_attempt_at.is_(None),
                    ),
                ),
            ))
            .order_by(AccountDeletionRequest.requested_at, AccountDeletionRequest.id)
            .limit(limit + 1)
        ).all())
        possible_backlog = len(candidate_ids) > limit
        candidate_ids = candidate_ids[:limit]
        summary = {"processed": 0, "completed": 0, "failed": 0, "possible_backlog": possible_backlog}
        for request_id in candidate_ids:
            # Compare-and-set claim prevents duplicate work across workers.
            claimed = _claim_deletion_request(
                db, request_id, now=now, stale_before=stale_processing_before
            )
            if claimed is None:
                continue

            summary["processed"] += 1
            try:
                if process_deletion_request(db, request_id, storage, claim_token=claimed):
                    summary["completed"] += 1
                else:
                    summary["failed"] += 1
            except DeletionClaimLost:
                # A newer worker owns the request; never reset its state to pending.
                db.rollback()
                summary["failed"] += 1
            except Exception:
                db.rollback()
                row = db.get(AccountDeletionRequest, request_id)
                if (
                    row is not None
                    and row.status == "processing"
                    and row.claim_token == claimed
                ):
                    _release_for_retry(row, "unexpected_processing_error")
                    row.claim_token = None
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
        f"processed={summary['processed']} completed={summary['completed']} failed={summary['failed']} "
        f"possible_backlog={str(summary.get('possible_backlog', False)).lower()}"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
