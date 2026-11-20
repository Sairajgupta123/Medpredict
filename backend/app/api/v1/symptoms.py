"""Non-diagnostic symptom phrase normalization endpoint."""

from fastapi import APIRouter, HTTPException

from app.schemas.symptom_analysis import (
    SymptomNormalizeRequest,
    SymptomNormalizeResponse,
)
from app.services.symptom_normalizer import normalize_symptoms

router = APIRouter(prefix="/symptoms", tags=["Symptom Input"])


@router.post("/normalize", response_model=SymptomNormalizeResponse)
def normalize_symptom_text(
    payload: SymptomNormalizeRequest,
) -> SymptomNormalizeResponse:
    """Map explicit phrases to a research vocabulary without diagnosing.

    Input is processed in memory only and is not persisted or logged by this route.
    Negated, historical and uncertain mentions are returned separately for review.
    """
    try:
        result = normalize_symptoms(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SymptomNormalizeResponse(
        **result,
        reported_context=payload.reported_context,
        disclaimer=(
            "This tool only recognizes a limited set of symptom phrases. "
            "It does not understand all medical context and does not diagnose, "
            "predict a disease, or recommend treatment. Review all information "
            "with a qualified healthcare professional."
        ),
    )
