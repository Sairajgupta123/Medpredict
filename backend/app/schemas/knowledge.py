"""Response schemas for reviewed medical knowledge."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class MedicalReferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    publisher: str
    url: HttpUrl
    evidence_type: str
    version: str
    published_on: date | None
    accessed_on: date
    next_review_due: date | None
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime


class CareRecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    version: str
    locale: str
    category: str
    urgency: str
    title: str
    content: str
    next_review_due: date | None
    references: list[MedicalReferenceRead] = Field(default_factory=list)


class RecommendationListResponse(BaseModel):
    items: list[CareRecommendationRead]
    total: int = Field(ge=0)
    disease_code: str
    disclaimer: str


class CatalogReferenceLinkRequest(BaseModel):
    """Request to link an existing medical source to a catalog entry."""

    target_type: str = Field(pattern="^(disease|symptom|disease_symptom)$")
    target_key: str = Field(min_length=1, max_length=200)
    reference_id: UUID
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return cleaned


class CatalogReferenceRemovalRequest(BaseModel):
    """Reason required to remove a catalog source link."""

    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return cleaned


class CatalogReferenceRead(BaseModel):
    """Source metadata and provenance for one catalog link."""

    id: UUID
    reference_id: UUID
    title: str
    publisher: str
    url: HttpUrl
    evidence_type: str
    version: str
    published_on: date | None
    accessed_on: date
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    next_review_due: date | None
    link_reason: str
    linked_by: UUID
    linked_at: datetime


class MedicalReferenceCreate(BaseModel):
    """Administrator-created source metadata; new records always start as drafts."""

    title: str = Field(min_length=3, max_length=300)
    publisher: str = Field(min_length=2, max_length=200)
    url: HttpUrl
    evidence_type: str = Field(min_length=2, max_length=80)
    version: str = Field(default="1", min_length=1, max_length=80)
    published_on: date | None = None
    accessed_on: date = Field(default_factory=date.today)
    license_name: str | None = Field(default=None, max_length=200)
    content_sha256: str | None = Field(default=None, pattern="^[a-fA-F0-9]{64}$")
    next_review_due: date | None = None

    @field_validator("title", "publisher", "evidence_type", "version")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned
