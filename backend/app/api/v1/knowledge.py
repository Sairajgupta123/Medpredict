"""Read-only access to approved, source-backed care information."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
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
    MedicalReferenceRead,
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
            MedicalReference.reviewed_by.is_not(None),
            MedicalReference.reviewed_at.is_not(None),
            (MedicalReference.next_review_due.is_(None))
            | (MedicalReference.next_review_due >= today),
        )
        .exists()
    )
    return (
        CareRecommendation.is_active.is_(True),
        CareRecommendation.review_status == "approved",
        CareRecommendation.reviewed_by.is_not(None),
        CareRecommendation.reviewed_at.is_not(None),
        (CareRecommendation.valid_from.is_(None))
        | (CareRecommendation.valid_from <= today),
        (CareRecommendation.valid_until.is_(None))
        | (CareRecommendation.valid_until >= today),
        (CareRecommendation.next_review_due.is_(None))
        | (CareRecommendation.next_review_due >= today),
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
            Disease.review_status == "approved",
            Disease.reviewed_by.is_not(None),
            Disease.reviewed_at.is_not(None),
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
    rows = db.scalars(statement).unique().all()

    # Serialize the link targets explicitly; link rows are not source records.
    items = []
    for item in rows:
        approved_sources = [
            link.reference for link in item.references
            if (
                link.reference.review_status == "approved"
                and link.reference.reviewed_by is not None
                and link.reference.reviewed_at is not None
                and (
                    link.reference.next_review_due is None
                    or link.reference.next_review_due >= date.today()
                )
            )
        ]
        if not approved_sources:
            continue
        items.append(
            CareRecommendationRead(
                id=item.id,
                code=item.code,
                version=item.version,
                locale=item.locale,
                category=item.category,
                urgency=item.urgency,
                title=item.title,
                content=item.content,
                next_review_due=item.next_review_due,
                references=[
                    MedicalReferenceRead.model_validate(source)
                    for source in approved_sources
                ],
            )
        )

    return RecommendationListResponse(
        items=items,
        total=len(items),
        disease_code=disease.code,
        disclaimer=PUBLIC_DISCLAIMER,
    )
