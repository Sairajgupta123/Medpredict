"""Registration, login, and current-user endpoints."""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.email import send_email_verification_email, send_password_reset_email
from app.core.auth_rate_limit import enforce_auth_rate_limit
from app.core.email_verification import (
    consume_email_verification_token,
    invalidate_email_verification_token,
    issue_email_verification_token,
)
from app.core.password_reset import (
    consume_password_reset_token,
    invalidate_password_reset_token,
    issue_password_reset_token,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.account_deletion import AccountDeletionRequest
from app.models.user import User
from app.models.prediction import Prediction, PredictionConsentEvent, PredictionResult, SkinImageAnalysis
from app.models.catalog import Disease
from app.schemas.auth import (
    AccountDeletionRequestPayload,
    EmailVerificationConfirmRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    TokenResponse,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)


def _token_response(user: User) -> TokenResponse:
    """Build a token response without exposing internal account fields."""
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.token_version),
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    """Create an account and return its access token."""
    enforce_auth_rate_limit(db, "register", payload.email, limit=5, window_seconds=3600)
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None
    return _token_response(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password",
)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    """Authenticate credentials and return a short-lived access token."""
    enforce_auth_rate_limit(db, "login", payload.email, limit=10, window_seconds=900)
    user = db.scalar(select(User).where(User.email == payload.email))
    stored_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, stored_hash)

    if (
        user is None
        or not password_valid
        or not user.is_active
        or (get_settings().require_verified_email and not user.email_verified)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _token_response(user)




@router.post(
    "/email-verification/request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request an email verification link",
)
def request_email_verification(
    payload: PasswordResetRequest,
    db: DbSession,
) -> dict[str, str]:
    """Send a generic response whether or not an unverified account exists."""
    enforce_auth_rate_limit(
        db, "email_verification", payload.email, limit=3, window_seconds=3600
    )
    generic_response = {
        "message": "If the account needs verification, instructions will be sent."
    }
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active or user.email_verified:
        return generic_response

    try:
        raw_token = issue_email_verification_token(db, user)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Email verification token creation failed.")
        return generic_response

    try:
        send_email_verification_email(user.email, raw_token)
    except Exception:
        try:
            invalidate_email_verification_token(db, raw_token)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Undelivered email verification token cleanup failed.")
        logger.warning("Email verification delivery failed.")
    return generic_response


@router.post(
    "/email-verification/confirm",
    status_code=status.HTTP_200_OK,
    summary="Verify an account email address",
)
def confirm_email_verification(
    payload: EmailVerificationConfirmRequest,
    db: DbSession,
) -> dict[str, str]:
    """Consume a valid single-use token and mark its account as verified."""
    user = consume_email_verification_token(db, payload.token)
    if user is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The email verification link is invalid or has expired.",
        )
    user.email_verified = True
    db.commit()
    return {"message": "Your email address has been verified."}


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset email",
)
def request_password_reset(
    payload: PasswordResetRequest,
    db: DbSession,
) -> dict[str, str]:
    """Return a generic response to prevent account/email enumeration."""
    enforce_auth_rate_limit(db, "password_reset", payload.email, limit=3, window_seconds=3600)
    generic_response = {
        "message": "If an account exists for this email, password reset instructions will be sent."
    }
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active:
        return generic_response

    try:
        raw_token = issue_password_reset_token(db, user)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Password reset token creation failed.")
        return generic_response

    try:
        send_password_reset_email(user.email, raw_token)
    except Exception:
        # A token that was not delivered must not remain usable. Invalidate only
        # this token so a concurrent, successfully delivered request is preserved.
        try:
            invalidate_password_reset_token(db, raw_token)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Undelivered password reset token cleanup failed.")
        # Do not log the recipient, reset URL, or raw token.
        logger.warning("Password reset email delivery failed.")
    return generic_response


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_200_OK,
    summary="Set a new password using a reset token",
)
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: DbSession,
) -> dict[str, str]:
    """Consume a one-time token and update the password in one transaction."""
    user = consume_password_reset_token(db, payload.token)
    if user is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The password reset link is invalid or has expired.",
        )

    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    db.commit()
    return {"message": "Your password has been reset successfully."}


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Log out and revoke the account's access tokens",
)
def logout(user: CurrentUser, db: DbSession) -> dict[str, str]:
    """Revoke all access tokens issued for the authenticated account."""
    user.token_version += 1
    db.commit()
    return {"message": "You have been logged out successfully."}


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get the authenticated user's profile",
)
def read_current_user(user: CurrentUser) -> UserRead:
    """Return the current user's safe profile fields."""
    return UserRead.model_validate(user)


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update the authenticated user's profile",
)
def update_current_user(
    payload: ProfileUpdateRequest,
    user: CurrentUser,
    db: DbSession,
) -> UserRead:
    """Update only profile fields explicitly supplied by the account owner."""
    if not payload.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one profile field must be supplied.",
        )

    user.display_name = payload.display_name
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)



@router.post(
    "/me/deletion-request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request deletion of the authenticated patient account",
)
def request_account_deletion(
    payload: AccountDeletionRequestPayload,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, str]:
    """Revoke access immediately and queue safe asynchronous account erasure."""
    if user.role != "patient":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-service deletion is currently available for patient accounts only.",
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    existing = db.scalar(
        select(AccountDeletionRequest).where(AccountDeletionRequest.user_id == user.id)
    )
    if existing is not None:
        if existing.status in {"pending", "processing"}:
            message = (
                "Your deletion request is being processed."
                if existing.status == "processing"
                else "Your deletion request is already queued."
            )
            return {"status": existing.status, "message": message}
        if existing.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This account's deletion request has already been completed.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This deletion request requires manual review. Please contact support.",
        )
    db.add(AccountDeletionRequest(user_id=user.id))
    user.is_active = False
    user.token_version += 1
    try:
        db.commit()
    except IntegrityError:
        # A second request can race between the existence check and insert.
        # The unique user_id constraint is the final concurrency guard; return
        # the already-created job state instead of leaking a 500 response.
        db.rollback()
        existing = db.scalar(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user.id
            )
        )
        if existing is not None and existing.status in {"pending", "processing"}:
            message = (
                "Your deletion request is being processed."
                if existing.status == "processing"
                else "Your deletion request is already queued."
            )
            return {"status": existing.status, "message": message}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A deletion request could not be created safely. Please retry or contact support.",
        ) from None
    return {
        "status": "pending",
        "message": "Your account is disabled. Personal data erasure is queued and may require storage retry.",
    }


@router.get("/me/export", summary="Export the authenticated user's account data")
def export_current_user_data(user: CurrentUser, db: DbSession, response: Response) -> dict:
    """Return a private, owner-scoped JSON export without internal storage secrets."""
    predictions = list(db.scalars(
        select(Prediction)
        .where(Prediction.user_id == user.id)
        .order_by(Prediction.created_at.asc(), Prediction.id.asc())
    ).all())
    prediction_ids = [item.id for item in predictions]
    result_rows = []
    consent_rows = []
    image_rows = []
    if prediction_ids:
        result_rows = db.execute(
            select(PredictionResult, Disease.code, Disease.name)
            .join(Disease, Disease.id == PredictionResult.disease_id)
            .where(PredictionResult.prediction_id.in_(prediction_ids))
            .order_by(PredictionResult.prediction_id, PredictionResult.rank)
        ).all()
        consent_rows = list(db.scalars(
            select(PredictionConsentEvent)
            .where(PredictionConsentEvent.prediction_id.in_(prediction_ids))
            .order_by(PredictionConsentEvent.captured_at.asc(), PredictionConsentEvent.id.asc())
        ).all())
        image_rows = list(db.scalars(
            select(SkinImageAnalysis).where(SkinImageAnalysis.prediction_id.in_(prediction_ids))
        ).all())

    results_by_prediction: dict[str, list[dict]] = {}
    for result, disease_code, disease_name in result_rows:
        results_by_prediction.setdefault(str(result.prediction_id), []).append({
            "rank": result.rank,
            "disease_code": disease_code,
            "disease_name": disease_name,
            "probability": str(result.probability),
            "explanation": result.explanation,
        })
    consents_by_prediction: dict[str, list[dict]] = {}
    for event in consent_rows:
        consents_by_prediction.setdefault(str(event.prediction_id), []).append({
            "purpose": event.purpose,
            "action": event.action,
            "policy_version": event.policy_version,
            "captured_at": event.captured_at,
        })
    images_by_prediction = {
        str(image.prediction_id): {
            "content_type": image.content_type,
            "storage_status": image.storage_status,
            "quality_status": image.quality_status,
            "review_required": image.review_required,
            "review_status": image.review_status,
            "review_outcome": image.review_outcome,
            "retention_expires_at": image.retention_expires_at,
            "deleted_at": image.deleted_at,
        }
        for image in image_rows
    }
    export_predictions = []
    for item in predictions:
        key = str(item.id)
        export_predictions.append({
            "id": key,
            "modality": item.modality,
            "status": item.status,
            "input_text": item.input_text,
            "input_storage_consent": item.input_storage_consent,
            "model_version": item.model_version,
            "disclaimer_version": item.disclaimer_version,
            "created_at": item.created_at,
            "completed_at": item.completed_at,
            "results": results_by_prediction.get(key, []),
            "image_metadata": images_by_prediction.get(key),
            "consent_events": consents_by_prediction.get(key, []),
        })
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="medipredict-account-export.json"'
    return {
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
            "display_name": user.display_name,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        },
        "predictions": export_predictions,
        "export_notes": [
            "This export contains the authenticated account's database records only.",
            "Private image bytes are not embedded; image metadata is included.",
            "Internal object-storage keys, access tokens, password hashes, and reviewer identifiers are excluded.",
        ],
    }
