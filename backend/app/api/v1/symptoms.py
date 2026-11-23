"""Non-diagnostic symptom vocabulary and phrase normalization endpoints."""

from fastapi import APIRouter, HTTPException

from app.api.dependencies import DbSession
from app.schemas.catalog_match import CatalogMatchRequest, CatalogMatchResponse
from app.schemas.symptom_analysis import (
    SymptomNormalizeRequest,
    SymptomNormalizeResponse,
)
from app.schemas.symptom_catalog import SymptomCatalogResponse
from app.services.catalog_match import match_approved_catalog
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



@router.post("/catalog-match", response_model=CatalogMatchResponse)
def compare_selected_symptoms_with_catalog(
    payload: CatalogMatchRequest,
    db: DbSession,
) -> CatalogMatchResponse:
    """Return research-only overlap with reviewed catalog associations.

    This is not a diagnostic or risk prediction model. Submitted IDs are
    processed for this request and are not persisted by this endpoint.
    """
    results = match_approved_catalog(db, payload.symptom_ids)
    return CatalogMatchResponse(
        method="approved_catalog_overlap",
        results=results,
        disclaimer=(
            "These results show only overlap with currently approved catalog "
            "associations. The ratio is not a probability, likelihood, or "
            "measure of disease risk. Catalog coverage may be incomplete and "
            "the method is not clinically validated. It does not diagnose or "
            "recommend treatment; consult a qualified healthcare professional."
        ),
    )
