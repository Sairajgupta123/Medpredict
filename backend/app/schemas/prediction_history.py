"""Safe response schemas for a user's prediction history."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PredictionHistoryItem(BaseModel):
    """History metadata; deliberately excludes symptom text and image keys."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    modality: str
    status: str
    model_version: str | None
    disclaimer_version: str | None
    created_at: datetime
    completed_at: datetime | None


class PredictionHistoryPage(BaseModel):
    """Paginated prediction history response."""

    items: list[PredictionHistoryItem]
    total: int
    limit: int
    offset: int


class ConsentRevocationResponse(BaseModel):
    """Confirmation that retained text has been removed."""

    prediction_id: UUID
    consent_revoked: bool
    retained_input_removed: bool
    message: str
