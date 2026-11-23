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
)


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
    image_record = db.scalar(
        select(SkinImageAnalysis).where(
            SkinImageAnalysis.prediction_id == prediction.id
        )
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
        if image_record.storage_status not in {"stored", "deletion_pending", "deleted"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The image storage state is not verified. The item is retained "
                    "for safe manual reconciliation."
                ),
            )

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
