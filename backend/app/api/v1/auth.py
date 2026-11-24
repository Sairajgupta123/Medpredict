"""Registration, login, and current-user endpoints."""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, HTTPException, status
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
from app.models.user import User
from app.schemas.auth import (
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
