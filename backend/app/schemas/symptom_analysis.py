"""Request and response schemas for conservative symptom phrase normalization."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SymptomNormalizeRequest(BaseModel):
    """Short-lived symptom text input; this endpoint does not persist it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=4000)


class NormalizedSymptom(BaseModel):
    id: str
    label: str
    category: str


class ContextualSymptomMention(NormalizedSymptom):
    context_flag: Literal[
        "negated_or_denied_context",
        "possibly_historical_context",
        "uncertain_context",
        "explicit_mention_unresolved",
    ]


class SymptomNormalizeResponse(BaseModel):
    taxonomy_version: str
    matched_symptoms: list[NormalizedSymptom]
    contextual_mentions: list[ContextualSymptomMention]
    unrecognized_text_present: bool
    review_required: bool
    reason: str
    clinical_interpretation_performed: Literal[False] = False
    disclaimer: str
