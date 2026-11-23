"""Request and response contracts for research-only catalog overlap."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CatalogMatchRequest(BaseModel):
    """Selected approved symptom identifiers; no free text is retained."""

    model_config = ConfigDict(extra="forbid")

    symptom_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("symptom_ids")
    @classmethod
    def validate_unique_ids(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("Symptom IDs cannot be blank.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Symptom IDs must be unique.")
        return cleaned


class CatalogMatchedSymptom(BaseModel):
    symptom_code: str
    symptom_name: str


class CatalogMatchItem(BaseModel):
    disease_code: str
    disease_name: str
    catalog_symptom_count: int
    matched_symptoms: list[CatalogMatchedSymptom]
    matched_symptom_count: int
    catalog_overlap_ratio: float = Field(ge=0, le=1)


class CatalogMatchResponse(BaseModel):
    method: Literal["approved_catalog_overlap"]
    results: list[CatalogMatchItem]
    disclaimer: str
    clinical_interpretation_performed: Literal[False] = False
    disease_probability_provided: Literal[False] = False
