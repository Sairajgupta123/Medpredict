"""Authentication and account profile API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """New account registration payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email casing and surrounding whitespace."""
        return value.strip().lower()

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        """Trim optional display names and reject whitespace-only values."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Display name cannot be blank.")
        return cleaned


class LoginRequest(BaseModel):
    """Email/password login payload."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetRequest(BaseModel):
    """Request a password recovery email."""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetConfirmRequest(BaseModel):
    """Confirm a password reset using the emailed one-time token."""

    token: str = Field(min_length=32, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    """Fields that a signed-in user may update on their own profile."""

    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        """Allow null to clear the name, but reject whitespace-only strings."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Display name cannot be blank.")
        return cleaned


class UserRead(BaseModel):
    """Safe public representation of the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: str
    display_name: str | None
    is_active: bool
    email_verified: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Bearer access token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
