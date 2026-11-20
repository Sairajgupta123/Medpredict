"""Response schemas for reviewed medical knowledge."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


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
    references: list[MedicalReferenceRead] = Field(default_factory=list)


class RecommendationListResponse(BaseModel):
    items: list[CareRecommendationRead]
    total: int = Field(ge=0)
    disease_code: str
    disclaimer: str
