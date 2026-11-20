"""Request and response schemas for administrator reviewer-scope governance."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


ReviewerScopeType = Literal["disease", "symptom", "disease_symptom"]


class ReviewerScopeCreate(BaseModel):
    """Grant one reviewer access to a catalog type or exact catalog key."""

    reviewer_id: UUID
    scope_type: ReviewerScopeType
    scope_key: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("scope_key")
    @classmethod
    def normalize_scope_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("scope_key must be omitted or contain a value")
        if ":" in cleaned and len(cleaned.split(":")) != 2:
            raise ValueError("disease_symptom scope keys must use DISEASE:SYMPTOM")
        return cleaned

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return cleaned


class ReviewerScopeRevoke(BaseModel):
    """Reason required to revoke an active reviewer scope."""

    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return cleaned


class ReviewerScopeRead(BaseModel):
    """Current grant state and its grant/revocation provenance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reviewer_id: UUID
    reviewer_email: str = ""
    scope_type: ReviewerScopeType
    scope_key: str | None
    granted_by: UUID
    grant_reason: str
    granted_at: datetime
    revoked_by: UUID | None
    revoked_at: datetime | None
    revoke_reason: str | None


class ReviewerScopeEventRead(BaseModel):
    """Immutable reviewer scope grant/revocation audit event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope_id: UUID
    reviewer_id: UUID
    event_type: Literal["granted", "revoked"]
    scope_type: ReviewerScopeType
    scope_key: str | None
    operator_id: UUID
    reason: str
    created_at: datetime
