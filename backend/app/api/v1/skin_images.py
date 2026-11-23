"""Authenticated, consent-gated skin-image intake."""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession
from app.models.prediction import Prediction, PredictionConsentEvent, SkinImageAnalysis
from app.services.skin_image_storage import (
    DisabledSkinImageStorage,
    SkinImageStorage,
    build_skin_image_object_key,
)
from app.services.skin_image_storage_factory import build_skin_image_storage
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
            prediction,
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
