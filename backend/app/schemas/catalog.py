"""Public read schemas for the curated disease and symptom catalog."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
