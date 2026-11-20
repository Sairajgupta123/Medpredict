"""Non-diagnostic symptom vocabulary and phrase normalization endpoints."""

from fastapi import APIRouter, HTTPException

from app.schemas.symptom_analysis import (
    SymptomNormalizeRequest,
    SymptomNormalizeResponse,
)
from app.schemas.symptom_catalog import SymptomCatalogResponse
from app.services.symptom_catalog import get_symptom_catalog
from app.services.symptom_normalizer import normalize_symptoms

router = APIRouter(prefix="/symptoms", tags=["Symptom Input"])


@router.get("/catalog", response_model=SymptomCatalogResponse)
def read_symptom_catalog() -> SymptomCatalogResponse:
    """Return selectable labels and stable IDs, never internal matching aliases."""
    return SymptomCatalogResponse(
        **get_symptom_catalog(),
    )


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
