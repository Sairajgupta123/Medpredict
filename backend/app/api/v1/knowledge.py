"""Read-only access to approved, source-backed care information."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.api.dependencies import DbSession
from app.models.catalog import Disease
from app.models.knowledge import (
    CareRecommendation,
    MedicalReference,
    RecommendationReference,
)
from app.schemas.knowledge import (
    CareRecommendationRead,
    RecommendationListResponse,
)

router = APIRouter(prefix="/knowledge", tags=["Reviewed Medical Knowledge"])

PUBLIC_DISCLAIMER = (
    "This information is general education, not a diagnosis or a treatment plan. "
    "It does not replace advice from a qualified healthcare professional. "
    "Seek urgent medical care for severe or rapidly worsening symptoms."
)


def _published_recommendation_filter(today: date):
    """Require active, approved, currently valid items with an approved source."""
    approved_source = (
        select(RecommendationReference.recommendation_id)
        .join(
            MedicalReference,
            MedicalReference.id == RecommendationReference.reference_id,
        )
        .where(
            RecommendationReference.recommendation_id == CareRecommendation.id,
            MedicalReference.review_status == "approved",
        )
        .exists()
    )
    return (
        CareRecommendation.is_active.is_(True),
        CareRecommendation.review_status == "approved",
        (CareRecommendation.valid_from.is_(None))
        | (CareRecommendation.valid_from <= today),
        (CareRecommendation.valid_until.is_(None))
        | (CareRecommendation.valid_until >= today),
        approved_source,
    )


@router.get(
    "/diseases/{disease_code}/recommendations",
    response_model=RecommendationListResponse,
)
def list_disease_recommendations(
    disease_code: str,
    db: DbSession,
    locale: Annotated[str, Query(min_length=2, max_length=12)] = "en",
    category: Annotated[str | None, Query(max_length=32)] = None,
) -> RecommendationListResponse:
    """Return only currently approved guidance with approved source records."""
    disease = db.scalar(
        select(Disease).where(
            Disease.code == disease_code,
            Disease.is_active.is_(True),
        )
    )
    if disease is None:
        raise HTTPException(status_code=404, detail="Supported condition not found.")

    filters = list(_published_recommendation_filter(date.today()))
    filters.extend(
        [
            CareRecommendation.disease_id == disease.id,
            CareRecommendation.locale == locale,
        ]
    )
    if category:
        filters.append(CareRecommendation.category == category)

    statement = (
        select(CareRecommendation)
        .where(*filters)
        .options(
            joinedload(CareRecommendation.references).joinedload(
                RecommendationReference.reference
            )
        )
        .order_by(CareRecommendation.category, CareRecommendation.title)
    )
    count_statement = (
        select(func.count(CareRecommendation.id)).where(*filters)
    )
    rows = db.scalars(statement).unique().all()
    total = db.scalar(count_statement) or 0

    # Return only approved references even if a recommendation has mixed provenance links.
    items = []
    for item in rows:
        approved_links = [
            link for link in item.references
            if link.reference.review_status == "approved"
        ]
        if not approved_links:
            continue
        serialized = CareRecommendationRead.model_validate(item)
        serialized.references = [
            link.reference for link in approved_links
        ]
        items.append(serialized)

    return RecommendationListResponse(
        items=items,
        total=len(items),
        disease_code=disease.code,
        disclaimer=PUBLIC_DISCLAIMER,
    )
