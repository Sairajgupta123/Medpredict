"""Authenticated, consent-gated skin-image intake."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import Administrator, CurrentUser, DbSession
from app.models.prediction import Prediction, PredictionConsentEvent, SkinImageAnalysis, SkinImageReviewEvent
from app.models.user import User
from app.services.skin_image_storage import (
    DisabledSkinImageStorage,
    SkinImageStorage,
    build_skin_image_object_key,
)
from app.services.skin_image_storage_factory import build_skin_image_storage
from app.services.prediction_history import get_owned_prediction, has_active_skin_image_consent
from app.services.skin_image_validation import (
    MAX_IMAGE_BYTES,
    assess_skin_image_quality,
    validate_and_sanitize_skin_image,
)

router = APIRouter(prefix="/skin-images", tags=["Skin image intake"])


class SkinImageIntakeResponse(BaseModel):
    """Safe intake response; never exposes the private object key or URL."""

    prediction_id: str
    status: str
    storage_status: str
    quality_warnings: list[str]
    clinical_interpretation_performed: bool = False
    disease_prediction_performed: bool = False
    message: str


@router.post("/intake", response_model=SkinImageIntakeResponse, status_code=201)
def intake_skin_image(
    user: CurrentUser,
    db: DbSession,
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP image; maximum 8 MiB")],
    processing_consent: Annotated[bool, Form()],
    history_consent: Annotated[bool, Form()],
    processing_policy_version: Annotated[str, Form(min_length=1, max_length=40)],
    history_policy_version: Annotated[str, Form(min_length=1, max_length=40)],
) -> SkinImageIntakeResponse:
    """Store a sanitized image only after separate processing and history consent.

    This endpoint performs intake and private storage only. It does not classify
    lesions, infer disease, or provide medical advice.
    """
    if not processing_consent or not history_consent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Separate image-processing and image-history consent are required.",
        )
    if not processing_policy_version.strip() or not history_policy_version.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both consent policy versions are required.",
        )

    raw_content = image.file.read(MAX_IMAGE_BYTES + 1)
    if len(raw_content) > MAX_IMAGE_BYTES:
        image.file.close()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds the 8 MiB upload limit.",
        )
    try:
        validated = validate_and_sanitize_skin_image(
            raw_content, image.content_type or ""
        )
        if validated.byte_size > MAX_IMAGE_BYTES:
            raise ValueError("Sanitized image exceeds the 8 MiB storage limit.")
        quality = assess_skin_image_quality(validated.content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    finally:
        image.file.close()

    storage: SkinImageStorage = build_skin_image_storage()
    if isinstance(storage, DisabledSkinImageStorage):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private image storage is not configured; the image was not retained.",
        )

    prediction = Prediction(
        user_id=user.id,
        modality="skin_image",
        status="review_required",
        input_storage_consent=False,
        disclaimer_version=None,
    )
    db.add(prediction)
    db.flush()
    image_id = uuid4()
    object_key = build_skin_image_object_key(image_id, validated.format)
    image_record = SkinImageAnalysis(
        id=image_id,
        prediction_id=prediction.id,
        object_key=object_key,
        content_type=validated.content_type,
        image_sha256=hashlib.sha256(validated.content).hexdigest(),
        storage_status="pending_upload",
        quality_status=(
            "advisory_warnings" if quality.warnings else "no_advisory_warnings"
        ),
        review_required=True,
    )
    db.add_all(
        [
            image_record,
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_processing",
                action="granted",
                policy_version=processing_policy_version.strip(),
            ),
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_history",
                action="granted",
                policy_version=history_policy_version.strip(),
            ),
        ]
    )
    db.commit()

    try:
        storage.put_private(object_key, validated.content, validated.content_type)
    except Exception as exc:
        image_record.storage_status = "failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private image storage failed. The intake record was retained for reconciliation.",
        ) from exc

    try:
        image_record.storage_status = "stored"
        db.commit()
    except Exception as exc:
        db.rollback()
        # The object may have been written while its DB status failed to commit.
        # Best-effort cleanup prevents an untracked private object; durable
        # reconciliation remains necessary for an outage during this cleanup.
        cleanup_succeeded = False
        try:
            storage.delete_private(object_key)
            cleanup_succeeded = True
        except Exception:
            cleanup_succeeded = False
        if not cleanup_succeeded:
            # Best-effort durable marker for an object that may still exist.
            try:
                image_record = db.scalar(
                    select(SkinImageAnalysis).where(
                        SkinImageAnalysis.object_key == object_key
                    )
                )
                if image_record is not None:
                    image_record.storage_status = "failed"
                    db.commit()
            except Exception:
                db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage confirmation failed; the request needs operational reconciliation.",
        ) from exc

    return SkinImageIntakeResponse(
        prediction_id=str(prediction.id),
        status="review_required",
        storage_status="stored",
        quality_warnings=list(quality.warnings),
        message=(
            "Image securely received for future review. No disease classification "
            "or clinical interpretation was performed."
        ),
    )


@router.get("/{prediction_id}", response_class=Response)
def retrieve_skin_image(
    prediction_id: str,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """Stream an owner's retained image only while image-history consent is active."""
    from uuid import UUID

    try:
        parsed_prediction_id = UUID(prediction_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image history item not found.",
        ) from exc

    prediction = get_owned_prediction(db, user.id, parsed_prediction_id)
    if prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image history item not found.",
        )
    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_history"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active image-history consent is required to retrieve this image.",
        )

    image_record = db.scalar(
        select(SkinImageAnalysis).where(
            SkinImageAnalysis.prediction_id == prediction.id
        )
    )
    if image_record is None or image_record.storage_status != "stored":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored image is not available.",
        )
    if image_record.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored image metadata failed validation.",
        )

    try:
        storage: SkinImageStorage = build_skin_image_storage()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private image storage is unavailable.",
        ) from exc
    if isinstance(storage, DisabledSkinImageStorage):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private image storage is not configured.",
        )
    try:
        content = storage.get_private(image_record.object_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private image retrieval is temporarily unavailable.",
        ) from exc

    if (
        not isinstance(content, bytes)
        or not content
        or len(content) > MAX_IMAGE_BYTES
        or hashlib.sha256(content).hexdigest() != image_record.image_sha256
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored image failed integrity validation.",
        )
    try:
        validated = validate_and_sanitize_skin_image(
            content, image_record.content_type
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored image failed format validation.",
        ) from exc
    if validated.content_type != image_record.content_type:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored image format does not match its recorded content type.",
        )

    return Response(
        content=content,
        media_type=image_record.content_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Content-Length": str(len(content)),
        },
    )


class SkinImageAssignmentRequest(BaseModel):
    reviewer_id: str
    reason: str


class SkinImageReviewDecisionRequest(BaseModel):
    outcome: str
    reason: str
    note: str | None = None


@router.get("/review/queue")
def list_skin_image_review_queue(
    user: CurrentUser,
    db: DbSession,
) -> list[dict]:
    """List only stored images assigned to this reviewer; admins can inspect all."""
    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Image reviewer permission required.")
    statement = (
        select(SkinImageAnalysis, Prediction)
        .join(Prediction, Prediction.id == SkinImageAnalysis.prediction_id)
        .where(
            SkinImageAnalysis.storage_status == "stored",
            SkinImageAnalysis.review_status == "assigned",
        )
        .order_by(SkinImageAnalysis.assigned_at.asc(), SkinImageAnalysis.id.asc())
    )
    if user.role != "admin":
        statement = statement.where(SkinImageAnalysis.assigned_reviewer_id == user.id)
    rows = db.execute(statement).all()
    results = []
    for image_record, prediction in rows:
        if not has_active_skin_image_consent(
            db, prediction.id, purpose="skin_image_processing"
        ):
            continue
        results.append({
            "prediction_id": str(prediction.id),
            "review_status": image_record.review_status,
            "quality_status": image_record.quality_status,
            "created_at": image_record.created_at,
            "assigned_at": image_record.assigned_at,
            "image_endpoint": f"/api/v1/skin-images/review/{prediction.id}/image",
        })
    return results


@router.post("/review/{prediction_id}/assign")
def assign_skin_image_review(
    prediction_id: str,
    payload: SkinImageAssignmentRequest,
    administrator: Administrator,
    db: DbSession,
) -> dict:
    """Assign or reassign a stored image to an active, verified reviewer."""
    from uuid import UUID

    try:
        parsed_id = UUID(prediction_id)
        reviewer_id = UUID(payload.reviewer_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid prediction or reviewer ID.") from exc
    reason = payload.reason.strip()
    if len(reason) < 8 or len(reason) > 1000:
        raise HTTPException(status_code=422, detail="Assignment reason must be 8–1,000 characters.")
    prediction = get_owned_prediction(db, administrator.id, parsed_id)
    # Admin assignment is cross-user by design; ownership helper is not applicable.
    raise HTTPException(status_code=501, detail="Assignment service is not yet available.")
