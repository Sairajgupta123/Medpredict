"""Public, non-diagnostic symptom vocabulary catalogue schemas."""

from pydantic import BaseModel


class SymptomCatalogItem(BaseModel):
    id: str
    label: str
    category: str


class SymptomCatalogResponse(BaseModel):
    taxonomy_version: str
    status: str
    language: str
    clinical_interpretation_performed: bool = False
    symptoms: list[SymptomCatalogItem]
    disclaimer: str
