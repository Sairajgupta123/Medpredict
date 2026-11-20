"""Public read schemas for the curated disease and symptom catalog."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CatalogItemRead(BaseModel):
    """Safe catalog item fields shared by diseases and symptoms."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None


class CatalogListResponse(BaseModel):
    """Paginated catalog response."""

    items: list[CatalogItemRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)

class DiseaseSymptomItemRead(BaseModel):
    """An approved symptom association for an approved disease."""

    symptom: CatalogItemRead
    relevance_weight: float




class CatalogReviewRequest(BaseModel):
    """Reviewer decision for a disease, symptom, or their association."""

    status: str = Field(pattern="^(draft|in_review|approved|retired)$")
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """Reject whitespace-only reasons and store normalized text."""
        cleaned = value.strip()
        if len(cleaned) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return cleaned


class CatalogReviewEventRead(BaseModel):
    """Auditable catalog review decision returned to authorized reviewers."""

    id: UUID
    target_type: str
    target_key: str
    previous_status: str
    new_status: str
    reason: str
    reviewer_id: UUID
    created_at: datetime
