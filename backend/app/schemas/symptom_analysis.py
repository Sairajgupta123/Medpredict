"""Request and response schemas for conservative symptom phrase normalization."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DurationValue = Literal[
    "less_than_24_hours",
    "one_to_three_days",
    "four_to_seven_days",
    "more_than_one_week",
    "not_sure",
]
SeverityValue = Literal["mild", "moderate", "severe", "not_sure"]
OnsetValue = Literal["sudden", "gradual", "comes_and_goes", "not_sure"]


class ReportedSymptomContext(BaseModel):
    """Self-reported context; values are not clinically interpreted."""

    duration: DurationValue
    severity: SeverityValue
    onset: OnsetValue


class SymptomNormalizeRequest(BaseModel):
    """Short-lived symptom text and self-reported context; never persisted here."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    reported_context: ReportedSymptomContext


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
    reported_context: ReportedSymptomContext
    clinical_interpretation_performed: Literal[False] = False
    disclaimer: str
