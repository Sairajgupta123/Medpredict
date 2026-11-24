"""Owner-scoped prediction history and consent operations."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.skin_image_storage import SkinImageStorage
from app.models.prediction import (
    Prediction,
    PredictionConsentEvent,
    PredictionResult,
    SkinImageAnalysis,
    SkinImageReviewEvent,
)
from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent


def list_user_history(
    db: Session, user_id: UUID, *, limit: int, offset: int
) -> tuple[list[Prediction], int]:
    """Return only the authenticated user's history, newest first."""
    base_query = select(Prediction).where(Prediction.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    items = list(
        db.scalars(
            base_query.order_by(Prediction.created_at.desc(), Prediction.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return items, total


def get_owned_prediction(db: Session, user_id: UUID, prediction_id: UUID) -> Prediction:
    """Resolve a prediction only when it belongs to the authenticated user."""
    prediction = db.scalar(
        select(Prediction).where(
            Prediction.id == prediction_id,
            Prediction.user_id == user_id,
        )
    )
    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction history item not found.",
        )
    return prediction


def revoke_text_history_consent(
    db: Session, user_id: UUID, prediction_id: UUID
) -> Prediction:
    """Revoke text retention and remove retained free text and result details."""
    prediction = get_owned_prediction(db, user_id, prediction_id)
    if prediction.modality != "text":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Consent revocation for image or combined history is unavailable "
                "until private object-storage deletion is configured."
            ),
        )

    latest_consent = db.scalar(
        select(PredictionConsentEvent)
        .where(
            PredictionConsentEvent.prediction_id == prediction.id,
            PredictionConsentEvent.purpose == "prediction_history",
        )
        .order_by(
            PredictionConsentEvent.captured_at.desc(),
            PredictionConsentEvent.id.desc(),
        )
        .limit(1)
    )
    if latest_consent is None or latest_consent.action != "granted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active history-storage consent exists for this item.",
        )

    prediction.input_text = None
    prediction.input_storage_consent = False
    db.query(PredictionResult).filter(
        PredictionResult.prediction_id == prediction.id
    ).delete(synchronize_session=False)
    db.add(
        PredictionConsentEvent(
            prediction_id=prediction.id,
            purpose="prediction_history",
            action="revoked",
            policy_version="history-v1",
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.refresh(prediction)
    return prediction


def delete_user_history_item(
    db: Session,
    user_id: UUID,
    prediction_id: UUID,
    *,
    image_storage: SkinImageStorage | None = None,
) -> None:
    """Delete owned history, removing any private image before its DB record.

    The deletion-pending commit is a durable retry marker. If object deletion
    succeeds but a later DB commit fails, the next attempt safely repeats the
    idempotent object deletion before removing the database record.
    """
    prediction = get_owned_prediction(db, user_id, prediction_id)
    # Lock against reviewer reads/assignments before marking the object pending.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == prediction.id)
        .with_for_update()
    )
    if image_record is not None:
        if image_storage is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This item includes a stored image reference. Deletion is "
                    "blocked until private object-storage cleanup is configured."
                ),
            )
        if image_record.storage_status not in {
            "pending_upload", "failed", "stored", "deletion_pending", "deleted"
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The image storage state is unknown. The item is retained "
                    "for safe manual reconciliation."
                ),
            )

        # Deleting owner history revokes every exact reviewer grant before
        # storage cleanup begins. The revocation and deletion-pending marker
        # commit together, so a failed object deletion cannot leave reviewer
        # access active while the owner is retrying cleanup.
        active_scopes = db.scalars(
            select(CatalogReviewerScope)
            .where(
                CatalogReviewerScope.scope_type == "skin_image",
                CatalogReviewerScope.scope_key == str(prediction.id),
                CatalogReviewerScope.revoked_at.is_(None),
            )
            .with_for_update()
        ).all()
        revocation_time = datetime.now(timezone.utc)
        revocation_reason = "Owner deleted image history; reviewer access revoked."
        for scope in active_scopes:
            scope.revoked_by = user_id
            scope.revoked_at = revocation_time
            scope.revoke_reason = revocation_reason
            db.add(CatalogReviewerScopeEvent(
                scope_id=scope.id,
                reviewer_id=scope.reviewer_id,
                event_type="revoked",
                scope_type=scope.scope_type,
                scope_key=scope.scope_key,
                operator_id=user_id,
                reason=revocation_reason,
            ))

        if image_record.storage_status != "deleted":
            image_record.storage_status = "deletion_pending"
            image_record.deletion_requested_at = (
                image_record.deletion_requested_at or datetime.now(timezone.utc)
            )
            db.commit()

            try:
                image_storage.delete_private(image_record.object_key)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Image deletion is pending and will need to be retried. "
                        "The history record has been retained."
                    ),
                ) from exc

            image_record.storage_status = "deleted"
            image_record.deleted_at = datetime.now(timezone.utc)
            db.commit()

    db.delete(prediction)
    db.commit()


def record_skin_image_consent_decision(
    db: Session,
    user_id: UUID,
    prediction_id: UUID,
    *,
    purpose: str,
    action: str,
    policy_version: str,
) -> PredictionConsentEvent:
    """Append an owner-scoped, versioned image consent decision.

    Processing consent, history-retention consent and human-review consent are
    intentionally independent. Callers must invoke this only after a clear user action.
    """
    prediction = get_owned_prediction(db, user_id, prediction_id)
    if prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Image consent applies only to image or combined predictions.",
        )
    if purpose not in {"skin_image_processing", "skin_image_history", "skin_image_review"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported image consent purpose.",
        )
    if action not in {"granted", "revoked"} or not policy_version.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid consent action and policy version are required.",
        )

    latest = db.scalar(
        select(PredictionConsentEvent)
        .where(
            PredictionConsentEvent.prediction_id == prediction.id,
            PredictionConsentEvent.purpose == purpose,
        )
        .order_by(
            PredictionConsentEvent.captured_at.desc(),
            PredictionConsentEvent.id.desc(),
        )
        .limit(1)
    )
    if action == "revoked" and (latest is None or latest.action != "granted"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active consent exists for this image purpose.",
        )

    event = PredictionConsentEvent(
        prediction_id=prediction.id,
        purpose=purpose,
        action=action,
        policy_version=policy_version.strip(),
        captured_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def has_active_skin_image_consent(
    db: Session, prediction_id: UUID, *, purpose: str
) -> bool:
    """Return whether the latest event grants the requested image purpose."""
    if purpose not in {"skin_image_processing", "skin_image_history", "skin_image_review"}:
        raise ValueError("Unsupported image consent purpose.")
    latest = db.scalar(
        select(PredictionConsentEvent)
        .where(
            PredictionConsentEvent.prediction_id == prediction_id,
            PredictionConsentEvent.purpose == purpose,
        )
        .order_by(
            PredictionConsentEvent.captured_at.desc(),
            PredictionConsentEvent.id.desc(),
        )
        .limit(1)
    )
    return latest is not None and latest.action == "granted"


def set_skin_image_retention_expiry(
    db: Session,
    user_id: UUID,
    prediction_id: UUID,
    *,
    expires_at: datetime,
    policy_version: str,
) -> SkinImageAnalysis:
    """Schedule expiry only when the owner explicitly granted image-history consent.

    The caller supplies the expiry and policy version; this service deliberately
    does not invent a medical-image retention duration.
    """
    prediction = get_owned_prediction(db, user_id, prediction_id)
    if prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Image retention applies only to image or combined predictions.",
        )
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Retention expiry must include a timezone.",
        )
    if expires_at <= datetime.now(timezone.utc) or not policy_version.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A future expiry and retention policy version are required.",
        )
    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_history"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active image-history consent is required to schedule retention.",
        )

    # Serialize retention updates with deletion and reviewer access.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == prediction.id)
        .with_for_update()
    )
    if image_record is None or image_record.storage_status != "stored":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a verified stored image can receive a retention schedule.",
        )

    image_record.retention_expires_at = expires_at.astimezone(timezone.utc)
    image_record.retention_policy_version = policy_version.strip()
    db.commit()
    db.refresh(image_record)
    return image_record


def list_expired_skin_image_records(
    db: Session, *, as_of: datetime, limit: int = 100
) -> list[SkinImageAnalysis]:
    """Find stored images whose explicit retention deadline has elapsed.

    The retention worker consumes this bounded candidate set and rechecks each
    row under a lock before deleting its private object. Unknown, failed, and
    in-flight states are intentionally excluded.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Expiry query timestamp must include a timezone.")
    if not 1 <= limit <= 500:
        raise ValueError("Expiry query limit must be between 1 and 500.")
    return list(
        db.scalars(
            select(SkinImageAnalysis)
            .where(
                SkinImageAnalysis.storage_status.in_({"stored", "deletion_pending"}),
                SkinImageAnalysis.retention_expires_at <= as_of,
                SkinImageAnalysis.retention_expires_at.is_not(None),
            )
            .order_by(SkinImageAnalysis.retention_expires_at, SkinImageAnalysis.id)
            .limit(limit)
        ).all()
    )


def revoke_skin_image_history_consent(
    db: Session,
    user_id: UUID,
    prediction_id: UUID,
    *,
    image_storage: SkinImageStorage,
    policy_version: str,
) -> Prediction:
    """Revoke image-history consent only after private object deletion succeeds.

    The image row is retained as a minimal audit/reconciliation record with a
    deleted state; its private object key is never returned by API schemas.
    """
    prediction = get_owned_prediction(db, user_id, prediction_id)
    if prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Image-history consent applies only to image or combined predictions.",
        )
    if not policy_version.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A consent policy version is required.",
        )
    # Serialize consent-driven object deletion with reviewer image access.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == prediction.id)
        .with_for_update()
    )
    # Re-read consent only after acquiring the image-row lock. Concurrent
    # revocation requests serialize here, so a waiter cannot append a duplicate
    # revocation event based on a stale pre-lock consent snapshot.
    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_history"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active image-history consent exists for this item.",
        )
    if image_record is None or image_record.storage_status not in {
        "stored", "deletion_pending", "deleted"
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The image storage state cannot be safely reconciled; manual review is required.",
        )

    # History-consent withdrawal removes the image from owner retention.
    # Revoke exact reviewer grants before storage cleanup, so a failed delete
    # cannot leave stale reviewer permissions active during reconciliation.
    active_scopes = db.scalars(
        select(CatalogReviewerScope)
        .where(
            CatalogReviewerScope.scope_type == "skin_image",
            CatalogReviewerScope.scope_key == str(prediction.id),
            CatalogReviewerScope.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    revoked_at = datetime.now(timezone.utc)
    revoke_reason = "Image-history consent revoked; reviewer access revoked."
    for scope in active_scopes:
        scope.revoked_by = user_id
        scope.revoked_at = revoked_at
        scope.revoke_reason = revoke_reason
        db.add(CatalogReviewerScopeEvent(
            scope_id=scope.id,
            reviewer_id=scope.reviewer_id,
            event_type="revoked",
            scope_type=scope.scope_type,
            scope_key=scope.scope_key,
            operator_id=user_id,
            reason=revoke_reason,
        ))

    if image_record.storage_status != "deleted":
        image_record.storage_status = "deletion_pending"
        image_record.deletion_requested_at = (
            image_record.deletion_requested_at or datetime.now(timezone.utc)
        )
        db.commit()
        try:
            image_storage.delete_private(image_record.object_key)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image deletion is pending. Consent remains active until deletion is confirmed.",
            ) from exc
        image_record.storage_status = "deleted"
        image_record.deleted_at = datetime.now(timezone.utc)
        db.commit()

    db.add(
        PredictionConsentEvent(
            prediction_id=prediction.id,
            purpose="skin_image_history",
            action="revoked",
            policy_version=policy_version.strip(),
            captured_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.refresh(prediction)
    return prediction


def purge_expired_skin_image_records(
    db: Session,
    *,
    image_storage: SkinImageStorage,
    as_of: datetime,
    limit: int = 100,
) -> dict[str, int]:
    """Delete expired private image objects in a bounded, retry-safe batch.

    Prediction and consent audit rows are retained. Failed objects remain in
    deletion_pending state for a later retry and are never reported as deleted.
    """
    candidates = list_expired_skin_image_records(db, as_of=as_of, limit=limit)
    deleted = 0
    failed = 0
    processed = 0
    for candidate in candidates:
        # Claim each row independently and keep its lock through object deletion.
        # This prevents two workers from deleting the same object concurrently.
        image_record = db.scalar(
            select(SkinImageAnalysis)
            .where(
                SkinImageAnalysis.id == candidate.id,
                SkinImageAnalysis.storage_status.in_({"stored", "deletion_pending"}),
                SkinImageAnalysis.retention_expires_at.is_not(None),
                SkinImageAnalysis.retention_expires_at <= as_of,
            )
            .with_for_update(skip_locked=True)
        )
        if image_record is None:
            continue

        processed += 1
        image_record.storage_status = "deletion_pending"
        image_record.deletion_requested_at = (
            image_record.deletion_requested_at or datetime.now(timezone.utc)
        )

        # Retention expiry ends reviewer assignment as well as storage access.
        # Preserve the outgoing reviewer in the append-only image audit trail.
        if (
            image_record.review_status == "assigned"
            and image_record.assigned_reviewer_id is not None
        ):
            previous_reviewer_id = image_record.assigned_reviewer_id
            image_record.assigned_reviewer_id = None
            image_record.assigned_by = None
            image_record.assigned_at = None
            image_record.review_status = "pending"
            db.add(SkinImageReviewEvent(
                prediction_id=image_record.prediction_id,
                image_analysis_id=image_record.id,
                event_type="unassigned",
                actor_id=None,
                assigned_reviewer_id=previous_reviewer_id,
                reason="Assignment cleared because the image retention period expired.",
            ))

        # Expiry is also an owner-authorized end to image retention. Revoke
        # exact reviewer scopes in the same durable transaction as the pending
        # marker, including when object storage is temporarily unavailable.
        active_scopes = db.scalars(
            select(CatalogReviewerScope)
            .where(
                CatalogReviewerScope.scope_type == "skin_image",
                CatalogReviewerScope.scope_key == str(image_record.prediction_id),
                CatalogReviewerScope.revoked_at.is_(None),
            )
            .with_for_update()
        ).all()
        owner_id = db.scalar(
            select(Prediction.user_id).where(Prediction.id == image_record.prediction_id)
        )
        if owner_id is None:
            raise RuntimeError("Expired image has no owning prediction.")
        revoked_at = datetime.now(timezone.utc)
        revoke_reason = "Image retention expired; reviewer access revoked."
        for scope in active_scopes:
            scope.revoked_by = owner_id
            scope.revoked_at = revoked_at
            scope.revoke_reason = revoke_reason
            db.add(CatalogReviewerScopeEvent(
                scope_id=scope.id,
                reviewer_id=scope.reviewer_id,
                event_type="revoked",
                scope_type=scope.scope_type,
                scope_key=scope.scope_key,
                operator_id=owner_id,
                reason=revoke_reason,
            ))
        db.commit()

        try:
            image_storage.delete_private(image_record.object_key)
        except Exception:
            failed += 1
            db.commit()
            continue

        image_record.storage_status = "deleted"
        image_record.deleted_at = datetime.now(timezone.utc)
        image_record.retention_expires_at = None
        latest_consent = db.scalar(
            select(PredictionConsentEvent)
            .where(
                PredictionConsentEvent.prediction_id == image_record.prediction_id,
                PredictionConsentEvent.purpose == "skin_image_history",
            )
            .order_by(
                PredictionConsentEvent.captured_at.desc(),
                PredictionConsentEvent.id.desc(),
            )
            .limit(1)
        )
        if latest_consent is not None and latest_consent.action == "granted":
            db.add(
                PredictionConsentEvent(
                    prediction_id=image_record.prediction_id,
                    purpose="skin_image_history",
                    action="revoked",
                    policy_version=(
                        image_record.retention_policy_version or "retention-expiry"
                    ),
                    captured_at=datetime.now(timezone.utc),
                )
            )
        db.commit()
        deleted += 1
    return {"processed": processed, "deleted": deleted, "failed": failed}
