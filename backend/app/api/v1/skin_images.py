"""Authenticated, consent-gated skin-image intake."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.api.dependencies import Administrator, CurrentUser, DbSession
from app.core.config import get_settings
from app.models.prediction import Prediction, PredictionConsentEvent, SkinImageAnalysis, SkinImageReviewEvent
from app.models.user import User
from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
from app.services.skin_image_storage import (
    DisabledSkinImageStorage,
    SkinImageStorage,
    build_skin_image_object_key,
)
from app.services.skin_image_storage_factory import build_skin_image_storage
from app.services.prediction_history import (
    get_owned_prediction,
    has_active_skin_image_consent,
)
from app.services.skin_image_validation import (
    MAX_IMAGE_BYTES,
    assess_skin_image_quality,
    validate_and_sanitize_skin_image,
)


router = APIRouter(prefix="/skin-images", tags=["Skin image intake"])


def _lock_active_reviewer_account(db: DbSession, user: User) -> User:
    """Serialize reviewer operations with administrator account deactivation."""
    if user.role != "reviewer":
        return user
    reviewer = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        reviewer is None
        or reviewer.role != "reviewer"
        or not reviewer.is_active
        or not reviewer.email_verified
    ):
        raise HTTPException(
            status_code=403,
            detail="An active, verified reviewer account is required.",
        )
    return reviewer


def _has_active_skin_image_review_scope(
    db: DbSession,
    reviewer: User,
    prediction_id,
) -> bool:
    """Require an explicit grant for this exact skin-image submission."""
    if (
        reviewer.role != "reviewer"
        or not reviewer.is_active
        or not reviewer.email_verified
    ):
        return False
    grant_id = db.scalar(
        select(CatalogReviewerScope.id)
        .where(
            CatalogReviewerScope.reviewer_id == reviewer.id,
            CatalogReviewerScope.scope_type == "skin_image",
            CatalogReviewerScope.revoked_at.is_(None),
            CatalogReviewerScope.scope_key == str(prediction_id),
        )
        .limit(1)
    )
    return grant_id is not None


class SkinImageIntakeResponse(BaseModel):
    """Safe intake response; never exposes the private object key or URL."""

    prediction_id: str
    status: str
    storage_status: str
    quality_warnings: list[str]
    clinical_interpretation_performed: bool = False
    disease_prediction_performed: bool = False
    message: str


class SkinImageModelStatusResponse(BaseModel):
    """Public capability metadata; never implies a model is clinically validated."""

    model_config = {"extra": "forbid"}

    inference_available: bool = False
    model_configured: bool = False
    disease_prediction_performed: bool = False
    clinical_validation_status: str = "not_established"
    human_review_required: bool = True
    image_intake_configured: bool = False
    image_retention_days: int | None = None
    message: str


@router.get("/model-status", response_model=SkinImageModelStatusResponse)
def read_skin_image_model_status() -> SkinImageModelStatusResponse:
    """Expose the current safe capability state without loading model artifacts."""
    settings = get_settings()
    intake_configured = bool(
        settings.skin_image_s3_bucket
        and settings.skin_image_s3_region
        and settings.skin_image_retention_days is not None
    )
    return SkinImageModelStatusResponse(
        image_intake_configured=intake_configured,
        image_retention_days=(settings.skin_image_retention_days if intake_configured else None),
        message=(
            "Skin-image classification is not configured. Image intake and "
            "technical quality checks do not produce a disease prediction."
        )
    )


@router.post("/intake", response_model=SkinImageIntakeResponse, status_code=201)
def intake_skin_image(
    user: CurrentUser,
    db: DbSession,
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP image; maximum 8 MiB")],
    processing_consent: Annotated[bool, Form()],
    history_consent: Annotated[bool, Form()],
    review_consent: Annotated[bool, Form()],
    processing_policy_version: Annotated[str, Form(min_length=1, max_length=40)],
    history_policy_version: Annotated[str, Form(min_length=1, max_length=40)],
    review_policy_version: Annotated[str, Form(min_length=1, max_length=40)],
) -> SkinImageIntakeResponse:
    """Store a sanitized image only after separate processing, history and human-review consent.

    This endpoint performs intake and private storage only. It does not classify
    lesions, infer disease, or provide medical advice.
    """
    if not processing_consent or not history_consent or not review_consent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Separate image-processing, image-history and human-review consent are required.",
        )
    if not processing_policy_version.strip() or not history_policy_version.strip() or not review_policy_version.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All three consent policy versions are required.",
        )

    settings = get_settings()
    if settings.skin_image_retention_days is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A reviewed image-retention period is not configured; the image was not accepted.",
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
        retention_expires_at=datetime.now(timezone.utc) + timedelta(days=settings.skin_image_retention_days),
        retention_policy_version="image-retention-v1",
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
            PredictionConsentEvent(
                prediction_id=prediction.id,
                purpose="skin_image_review",
                action="granted",
                policy_version=review_policy_version.strip(),
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


@router.post("/{prediction_id}/revoke-review-consent")
def revoke_skin_image_review_consent(
    prediction_id: str,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    """Revoke human-review permission and disable all reviewer scopes for this image."""
    from uuid import UUID

    try:
        parsed_id = UUID(prediction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Image history item not found.") from exc
    prediction = get_owned_prediction(db, user.id, parsed_id)
    if prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(status_code=409, detail="Human image-review consent applies only to image submissions.")

    # Serialize consent withdrawal with reviewer assignment, which locks this
    # same image row before checking consent and creating an access scope.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == prediction.id)
        .with_for_update()
    )
    latest_consent = db.scalar(
        select(PredictionConsentEvent)
        .where(
            PredictionConsentEvent.prediction_id == prediction.id,
            PredictionConsentEvent.purpose == "skin_image_review",
        )
        .order_by(
            PredictionConsentEvent.captured_at.desc(),
            PredictionConsentEvent.id.desc(),
        )
        .limit(1)
    )
    if latest_consent is None or latest_consent.action != "granted":
        raise HTTPException(
            status_code=409,
            detail="No active consent exists for this image purpose.",
        )

    event = PredictionConsentEvent(
        prediction_id=prediction.id,
        purpose="skin_image_review",
        action="revoked",
        policy_version="image-review-v1",
        captured_at=datetime.now(timezone.utc),
    )
    db.add(event)

    # Keep the consent event and every scope revocation in the same transaction.
    # The image-row lock prevents assignment from slipping between these writes.
    if image_record is not None:
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
                prediction_id=prediction.id,
                image_analysis_id=image_record.id,
                event_type="unassigned",
                actor_id=user.id,
                assigned_reviewer_id=previous_reviewer_id,
                reason="Assignment cleared because the owner revoked human-review consent.",
            ))
    # Revoke all exact-image scopes even if the image metadata row is
    # missing. Consent is the authorization source of truth; stale grants
    # should not survive a withdrawal just because metadata is unavailable.
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
    for scope in active_scopes:
        reason = "Image owner revoked human-review consent."
        scope.revoked_by = user.id
        scope.revoked_at = revoked_at
        scope.revoke_reason = reason
        db.add(CatalogReviewerScopeEvent(
            scope_id=scope.id,
            reviewer_id=scope.reviewer_id,
            event_type="revoked",
            scope_type="skin_image",
            scope_key=str(prediction.id),
            operator_id=user.id,
            reason=reason,
        ))
    db.commit()
    return {
        "prediction_id": str(prediction.id),
        "purpose": event.purpose,
        "consent_status": "revoked",
        "reviewer_access_revoked": True,
        "message": "Human review is disabled for this image. Existing audit records are retained.",
    }


@router.get("/{prediction_id:uuid}", response_class=Response)
def retrieve_skin_image(
    prediction_id: UUID,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """Stream an owner's retained image only while image-history consent is active."""
    parsed_prediction_id = prediction_id

    prediction = get_owned_prediction(db, user.id, parsed_prediction_id)
    if prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image history item not found.",
        )
    # Serialize owner retrieval with history-consent revocation and deletion.
    # Re-check consent only after taking the same image-row lock used by the
    # revocation path, so a stale pre-lock grant cannot authorize a new read.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == prediction.id)
        .with_for_update()
    )
    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_history"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active image-history consent is required to retrieve this image.",
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
            "Cross-Origin-Resource-Policy": "same-origin",
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


@router.get("/review/queue")
def list_skin_image_review_queue(
    user: CurrentUser,
    db: DbSession,
) -> list[dict]:
    """List assigned images for reviewers and pending/assigned items for admins."""
    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Image reviewer permission required.")
    user = _lock_active_reviewer_account(db, user)
    statement = (
        select(SkinImageAnalysis, Prediction)
        .join(Prediction, Prediction.id == SkinImageAnalysis.prediction_id)
        .where(
            SkinImageAnalysis.storage_status == "stored",
            SkinImageAnalysis.review_status.in_(
                ["pending", "assigned"] if user.role == "admin" else ["assigned"]
            ),
        )
        .order_by(SkinImageAnalysis.assigned_at.asc(), SkinImageAnalysis.id.asc())
        # Keep queue visibility consistent with consent revocation, assignment,
        # and reviewer deactivation, all of which serialize on the image row.
        .with_for_update(of=SkinImageAnalysis)
    )
    if user.role != "admin":
        statement = statement.where(SkinImageAnalysis.assigned_reviewer_id == user.id)
    rows = db.execute(statement).all()
    results = []
    for image_record, prediction in rows:
        if not has_active_skin_image_consent(
            db, prediction.id, purpose="skin_image_processing"
        ) or not has_active_skin_image_consent(
            db, prediction.id, purpose="skin_image_review"
        ):
            continue
        if user.role != "admin" and not _has_active_skin_image_review_scope(
            db, user, prediction.id
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
    prediction = db.get(Prediction, parsed_id)
    if prediction is None or prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(status_code=404, detail="Skin image review item not found.")
    # Match grant/deactivation lock order: reviewer account first, image second.
    reviewer = db.scalar(
        select(User)
        .where(
            User.id == reviewer_id,
            User.role == "reviewer",
            User.is_active.is_(True),
            User.email_verified.is_(True),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if reviewer is None:
        raise HTTPException(status_code=404, detail="Active verified reviewer not found.")
    image_record = db.scalar(
        select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == prediction.id).with_for_update()
    )
    if image_record is None or image_record.storage_status != "stored":
        raise HTTPException(status_code=409, detail="Only stored images can be assigned for review.")
    if image_record.review_status in {"reviewed", "unable_to_assess"}:
        raise HTTPException(status_code=409, detail="This image review is already completed.")
    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_processing"
    ) or not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_review"
    ):
        raise HTTPException(
            status_code=403,
            detail="Active image-processing and human-review consent are required.",
        )
    if not _has_active_skin_image_review_scope(db, reviewer, prediction.id):
        raise HTTPException(
            status_code=403,
            detail="Reviewer does not have an active skin-image review scope.",
        )
    previous_reviewer_id = image_record.assigned_reviewer_id
    if previous_reviewer_id is not None and previous_reviewer_id != reviewer.id:
        # Keep the outgoing reviewer explicit in image-level audit history before
        # recording the incoming assignment below.
        db.add(SkinImageReviewEvent(
            prediction_id=prediction.id,
            image_analysis_id=image_record.id,
            event_type="unassigned",
            actor_id=administrator.id,
            assigned_reviewer_id=previous_reviewer_id,
            reason="Assignment cleared because the image was reassigned.",
        ))
        previous_scope = db.scalar(
            select(CatalogReviewerScope)
            .where(
                CatalogReviewerScope.reviewer_id == previous_reviewer_id,
                CatalogReviewerScope.scope_type == "skin_image",
                CatalogReviewerScope.scope_key == str(prediction.id),
                CatalogReviewerScope.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if previous_scope is not None:
            revocation_reason = "Exact image access revoked after reassignment."
            previous_scope.revoked_by = administrator.id
            previous_scope.revoked_at = datetime.now(timezone.utc)
            previous_scope.revoke_reason = revocation_reason
            db.add(CatalogReviewerScopeEvent(
                scope_id=previous_scope.id,
                reviewer_id=previous_reviewer_id,
                event_type="revoked",
                scope_type="skin_image",
                scope_key=str(prediction.id),
                operator_id=administrator.id,
                reason=revocation_reason,
            ))
    image_record.assigned_reviewer_id = reviewer.id
    image_record.assigned_by = administrator.id
    image_record.assigned_at = datetime.now(timezone.utc)
    image_record.review_status = "assigned"
    db.add(SkinImageReviewEvent(
        prediction_id=prediction.id,
        image_analysis_id=image_record.id,
        event_type="reassigned" if previous_reviewer_id else "assigned",
        actor_id=administrator.id,
        assigned_reviewer_id=reviewer.id,
        reason=reason,
    ))
    db.commit()
    return {
        "prediction_id": str(prediction.id),
        "reviewer_id": str(reviewer.id),
        "review_status": image_record.review_status,
    }


@router.post("/review/{prediction_id}/decision")
def submit_skin_image_review(
    prediction_id: str,
    payload: SkinImageReviewDecisionRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    """Record a non-diagnostic technical image review by its assignee or admin."""
    from uuid import UUID

    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Image reviewer permission required.")
    user = _lock_active_reviewer_account(db, user)
    try:
        parsed_id = UUID(prediction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Skin image review item not found.") from exc
    reason = payload.reason.strip()
    if len(reason) < 8 or len(reason) > 1000:
        raise HTTPException(status_code=422, detail="Review reason must be 8–1,000 characters.")
    if payload.outcome not in {"capture_adequate", "unable_to_assess"}:
        raise HTTPException(status_code=422, detail="Outcome must be capture_adequate or unable_to_assess.")
    prediction = db.get(Prediction, parsed_id)
    if prediction is None or prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(status_code=404, detail="Skin image review item not found.")
    image_record = db.scalar(
        select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id == prediction.id).with_for_update()
    )
    if image_record is None or image_record.storage_status != "stored":
        raise HTTPException(status_code=409, detail="Stored image is not available for review.")
    if user.role != "admin" and image_record.assigned_reviewer_id != user.id:
        raise HTTPException(status_code=404, detail="Assigned review item not found.")
    if user.role != "admin" and not _has_active_skin_image_review_scope(
        db, user, prediction.id
    ):
        raise HTTPException(status_code=403, detail="Active skin-image review scope required.")
    if image_record.review_status != "assigned":
        raise HTTPException(status_code=409, detail="Image is not awaiting review.")
    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_processing"
    ) or not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_review"
    ):
        raise HTTPException(
            status_code=403,
            detail="Active image-processing and human-review consent are required.",
        )
    image_record.review_outcome = payload.outcome
    image_record.review_status = "reviewed" if payload.outcome == "capture_adequate" else "unable_to_assess"
    image_record.reviewed_at = datetime.now(timezone.utc)
    db.add(SkinImageReviewEvent(
        prediction_id=prediction.id,
        image_analysis_id=image_record.id,
        event_type="reviewed",
        actor_id=user.id,
        assigned_reviewer_id=image_record.assigned_reviewer_id,
        outcome=payload.outcome,
        reason=reason,
    ))
    db.commit()
    return {
        "prediction_id": str(prediction.id),
        "review_status": image_record.review_status,
        "review_outcome": image_record.review_outcome,
        "reviewed_at": image_record.reviewed_at,
        "clinical_interpretation_performed": False,
        "disease_prediction_performed": False,
    }


@router.get("/review/{prediction_id}/image", response_class=Response)
def retrieve_assigned_review_image(
    prediction_id: str,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """Return image bytes only to its assigned reviewer or an administrator."""
    from uuid import UUID

    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Image reviewer permission required.")
    user = _lock_active_reviewer_account(db, user)
    try:
        parsed_id = UUID(prediction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Review image not found.") from exc
    prediction = db.get(Prediction, parsed_id)
    if prediction is None or prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(status_code=404, detail="Review image not found.")
    # Hold the same image-row lock used by assignment and consent revocation
    # until the access audit event commits. This prevents bytes being served
    # after a concurrent consent withdrawal has committed.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == prediction.id)
        .with_for_update()
    )
    if (
        image_record is None
        or image_record.storage_status != "stored"
        or image_record.review_status != "assigned"
        or (user.role != "admin" and image_record.assigned_reviewer_id != user.id)
    ):
        raise HTTPException(status_code=404, detail="Assigned review image not found.")
    if user.role != "admin" and not _has_active_skin_image_review_scope(
        db, user, prediction.id
    ):
        raise HTTPException(status_code=403, detail="Active skin-image review scope required.")
    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_processing"
    ) or not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_review"
    ):
        raise HTTPException(
            status_code=403,
            detail="Active image-processing and human-review consent are required.",
        )
    try:
        storage = build_skin_image_storage()
        if isinstance(storage, DisabledSkinImageStorage):
            raise RuntimeError("Private image storage is disabled.")
        content = storage.get_private(image_record.object_key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Private review image is unavailable.") from exc
    if (
        not isinstance(content, bytes)
        or not content
        or len(content) > MAX_IMAGE_BYTES
        or hashlib.sha256(content).hexdigest() != image_record.image_sha256
    ):
        raise HTTPException(status_code=503, detail="Review image failed integrity validation.")
    try:
        validated = validate_and_sanitize_skin_image(content, image_record.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Review image failed format validation.") from exc
    if validated.content_type != image_record.content_type:
        raise HTTPException(status_code=503, detail="Review image format metadata is inconsistent.")
    db.add(SkinImageReviewEvent(
        prediction_id=prediction.id,
        image_analysis_id=image_record.id,
        event_type="image_accessed",
        actor_id=user.id,
        assigned_reviewer_id=image_record.assigned_reviewer_id,
        reason="Authorized private image retrieval completed.",
    ))
    db.commit()
    return Response(
        content=content,
        media_type=image_record.content_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/review/{prediction_id}/events")
def list_skin_image_review_events(
    prediction_id: str,
    user: CurrentUser,
    db: DbSession,
) -> list[dict]:
    """Read the review audit trail only for the assigned reviewer or an admin."""
    from uuid import UUID

    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Image reviewer permission required.")
    user = _lock_active_reviewer_account(db, user)
    try:
        parsed_id = UUID(prediction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Review history not found.") from exc
    # Serialize audit-history reads with consent withdrawal and reassignment.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == parsed_id)
        .with_for_update()
    )
    if image_record is None or (
        user.role != "admin" and image_record.assigned_reviewer_id != user.id
    ):
        raise HTTPException(status_code=404, detail="Assigned review history not found.")
    if user.role != "admin" and not _has_active_skin_image_review_scope(
        db, user, parsed_id
    ):
        raise HTTPException(status_code=403, detail="Active skin-image review scope required.")
    if user.role != "admin" and not has_active_skin_image_consent(
        db, parsed_id, purpose="skin_image_review"
    ):
        raise HTTPException(status_code=403, detail="Active human-review consent is required.")
    rows = db.execute(
        select(SkinImageReviewEvent, User)
        .join(User, User.id == SkinImageReviewEvent.actor_id)
        .where(SkinImageReviewEvent.prediction_id == parsed_id)
        .order_by(SkinImageReviewEvent.created_at.asc(), SkinImageReviewEvent.id.asc())
    ).all()
    return [
        {
            "event_type": event.event_type,
            "actor_id": (
                str(event.actor_id)
                if user.role == "admin" or actor.role != "patient"
                else None
            ),
            "assigned_reviewer_id": (
                str(event.assigned_reviewer_id)
                if event.assigned_reviewer_id is not None
                and (user.role == "admin" or event.assigned_reviewer_id == user.id)
                else None
            ),
            "outcome": event.outcome,
            "reason": event.reason,
            "created_at": event.created_at,
        }
        for event, actor in rows
    ]


@router.get("/review/audit")
def list_skin_image_review_audit(
    user: CurrentUser,
    db: DbSession,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List image-review audit events for admins or the reviewer's own assignments.

    Reviewer access is restricted to events where they were the actor or the
    assigned reviewer. Administrators can inspect the complete image-review
    audit trail. No image bytes, object keys, or patient identity are returned.
    """
    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Image reviewer permission required.")
    user = _lock_active_reviewer_account(db, user)
    if limit < 1 or limit > 200 or offset < 0 or offset > 10000:
        raise HTTPException(status_code=422, detail="Audit pagination is outside the allowed range.")

    statement = (
        select(SkinImageReviewEvent, User)
        .join(User, User.id == SkinImageReviewEvent.actor_id)
        .order_by(
            SkinImageReviewEvent.created_at.desc(),
            SkinImageReviewEvent.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    if user.role != "admin":
        statement = statement.where(
            or_(
                SkinImageReviewEvent.actor_id == user.id,
                SkinImageReviewEvent.assigned_reviewer_id == user.id,
            )
        )
    rows = db.execute(statement).all()
    return [
        {
            "event_id": str(event.id),
            "prediction_id": str(event.prediction_id),
            "event_type": event.event_type,
            # Patient identifiers are not needed for reviewer audit work.
            # Staff retain attribution; admins retain the complete audit trail.
            "actor_id": (
                str(event.actor_id)
                if user.role == "admin" or actor.role != "patient"
                else None
            ),
            "actor_identity": (
                (actor.display_name or actor.email)
                if user.role == "admin" or actor.role != "patient"
                else None
            ),
            "actor_role": actor.role,
            # Never disclose another reviewer's stable identifier to a reviewer.
            "assigned_reviewer_id": (
                str(event.assigned_reviewer_id)
                if event.assigned_reviewer_id is not None
                and (user.role == "admin" or event.assigned_reviewer_id == user.id)
                else None
            ),
            "outcome": event.outcome,
            "reason": event.reason,
            "created_at": event.created_at,
        }
        for event, actor in rows
    ]


@router.get("/{prediction_id}/review-status")
def get_owner_skin_image_review_status(
    prediction_id: str,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    """Return a minimal, owner-only status for a skin-image technical review.

    Reviewer identities, internal reasons, audit events, storage references,
    image bytes and diagnostic fields are intentionally excluded.
    """
    from uuid import UUID

    try:
        parsed_id = UUID(prediction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Image history item not found.") from exc

    prediction = get_owned_prediction(db, user.id, parsed_id)
    if prediction.modality not in {"skin_image", "combined"}:
        raise HTTPException(status_code=404, detail="Image history item not found.")

    # Serialize this status snapshot with consent withdrawal and reviewer
    # assignment, which lock the same image row before changing access state.
    image_record = db.scalar(
        select(SkinImageAnalysis)
        .where(SkinImageAnalysis.prediction_id == prediction.id)
        .with_for_update()
    )
    if image_record is None:
        raise HTTPException(status_code=404, detail="Image history item not found.")

    if not has_active_skin_image_consent(
        db, prediction.id, purpose="skin_image_review"
    ):
        return {
            "prediction_id": str(prediction.id),
            "status": "review_access_withdrawn",
            "status_label": "Human review permission withdrawn",
            "status_detail": "The image is no longer available to reviewers under your current consent settings.",
            "next_step": "No further review will take place unless you choose to submit a new image with the required permissions.",
            "status_at": None,
            "clinical_interpretation_performed": False,
            "disease_prediction_performed": False,
        }

    if image_record.storage_status != "stored":
        status_value = "submission_unavailable"
        status_label = "Image is not currently available for technical review"
        status_detail = "The stored image is unavailable, so a technical review could not proceed."
        next_step = "Please contact the MediPredict support team if you need help with this submission."
        status_at = image_record.created_at
    elif image_record.review_status == "pending":
        status_value = "awaiting_review"
        status_label = "Awaiting technical image review"
        status_detail = "Your image has been received. A technical capture-quality review has not started yet."
        next_step = "You do not need to take any action while the review is pending. Seek medical care independently if you have symptoms or concerns."
        status_at = image_record.created_at
    elif image_record.review_status == "assigned":
        status_value = "assigned"
        status_label = "Assigned for technical image review"
        status_detail = "The submission has been assigned for a technical capture-quality check."
        next_step = "No action is required for the review itself. Do not delay medical care for symptoms or concerns."
        status_at = image_record.assigned_at or image_record.created_at
    elif image_record.review_status == "reviewed" and image_record.review_outcome == "capture_adequate":
        status_value = "reviewed"
        status_label = "Technical image capture review completed"
        status_detail = "The reviewer marked the image capture as technically adequate for this limited review. This does not establish whether a skin condition is present or what it may be."
        next_step = "If you have a skin concern, consult a qualified healthcare professional; this technical review is not a medical assessment."
        status_at = image_record.reviewed_at
    else:
        status_value = "unable_to_assess"
        status_label = "Image quality could not be assessed"
        status_detail = "The reviewer could not complete the technical capture-quality check from this image."
        next_step = "If you choose to submit another image, use clear focus, even lighting and no filters. Seek medical care independently if you have symptoms or concerns."
        status_at = image_record.reviewed_at

    return {
        "prediction_id": str(prediction.id),
        "status": status_value,
        "status_label": status_label,
        "status_detail": status_detail,
        "next_step": next_step,
        "status_at": status_at,
        "clinical_interpretation_performed": False,
        "disease_prediction_performed": False,
    }
