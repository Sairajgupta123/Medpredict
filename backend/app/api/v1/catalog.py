"""Public catalog reads and authorized catalog review actions."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.dependencies import CatalogReviewer, DbSession
from app.models.catalog import Disease, DiseaseSymptom, Symptom
from app.schemas.catalog import (
    CatalogItemRead,
    CatalogListResponse,
    DiseaseSymptomItemRead,
    CatalogReviewRequest,
)

router = APIRouter(prefix="/catalog", tags=["Medical Catalog"])


def _list_catalog_items(
    db: DbSession,
    model: type[Disease] | type[Symptom],
    query: str | None,
    limit: int,
    offset: int,
) -> CatalogListResponse:
    """Return active entries only after explicit, audited approval."""
    statement = select(model).where(model.is_active.is_(True))
    count_statement = select(func.count()).select_from(model).where(
        model.is_active.is_(True)
    )

    # The packaged symptom phrase taxonomy is research-only. The database-backed
    # symptom catalogue is a separate publication channel and must never expose
    # drafts, in-review records, or retired entries.
    if model in (Disease, Symptom):
        statement = statement.where(
            model.review_status == "approved",
            model.reviewed_by.is_not(None),
            model.reviewed_at.is_not(None),
        )
        count_statement = count_statement.where(
            model.review_status == "approved",
            model.reviewed_by.is_not(None),
            model.reviewed_at.is_not(None),
        )

    cleaned_query = query.strip() if query else ""
    if cleaned_query:
        search_pattern = f"%{cleaned_query}%"
        statement = statement.where(
            (model.name.ilike(search_pattern))
            | (model.code.ilike(search_pattern))
        )
        count_statement = count_statement.where(
            (model.name.ilike(search_pattern))
            | (model.code.ilike(search_pattern))
        )

    total = db.scalar(count_statement) or 0
    rows = db.scalars(
        statement.order_by(model.name.asc()).limit(limit).offset(offset)
    ).all()

    return CatalogListResponse(
        items=[CatalogItemRead.model_validate(item) for item in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/symptoms", response_model=CatalogListResponse)
def list_symptoms(
    db: DbSession,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CatalogListResponse:
    """Search active, explicitly approved symptom terms only."""
    return _list_catalog_items(db, Symptom, q, limit, offset)


@router.get("/diseases", response_model=CatalogListResponse)
def list_diseases(
    db: DbSession,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CatalogListResponse:
    """Browse active, explicitly approved supported conditions only."""
    return _list_catalog_items(db, Disease, q, limit, offset)

@router.get(
    "/diseases/{disease_code}/symptoms",
    response_model=list[DiseaseSymptomItemRead],
)
def list_approved_disease_symptoms(
    disease_code: str,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[DiseaseSymptomItemRead]:
    """Return only reviewed links between an approved disease and symptoms."""
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

    rows = db.execute(
        select(DiseaseSymptom, Symptom)
        .join(Symptom, Symptom.id == DiseaseSymptom.symptom_id)
        .where(
            DiseaseSymptom.disease_id == disease.id,
            DiseaseSymptom.review_status == "approved",
            DiseaseSymptom.reviewed_by.is_not(None),
            DiseaseSymptom.reviewed_at.is_not(None),
            Symptom.is_active.is_(True),
            Symptom.review_status == "approved",
            Symptom.reviewed_by.is_not(None),
            Symptom.reviewed_at.is_not(None),
        )
        .order_by(Symptom.name.asc())
        .limit(limit)
    ).all()

    return [
        DiseaseSymptomItemRead(
            symptom=CatalogItemRead.model_validate(symptom),
            relevance_weight=link.relevance_weight,
        )
        for link, symptom in rows
    ]

def _apply_review_decision(item, payload: CatalogReviewRequest, reviewer) -> dict:
    """Apply a reviewer decision and bind approval metadata to the actor."""
    item.review_status = payload.status
    if payload.status == "approved":
        item.reviewed_by = str(reviewer.id)
        item.reviewed_at = datetime.now(timezone.utc)
    else:
        item.reviewed_by = None
        item.reviewed_at = None
    return {
        "review_status": item.review_status,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": item.reviewed_at,
    }


@router.patch("/review/diseases/{disease_code}")
def review_disease(
    disease_code: str,
    payload: CatalogReviewRequest,
    reviewer: CatalogReviewer,
    db: DbSession,
) -> dict:
    """Change disease publication state; only provisioned reviewers may act."""
    item = db.scalar(select(Disease).where(Disease.code == disease_code))
    if item is None:
        raise HTTPException(status_code=404, detail="Disease not found.")
    result = _apply_review_decision(item, payload, reviewer)
    db.commit()
    return result


@router.patch("/review/symptoms/{symptom_code}")
def review_symptom(
    symptom_code: str,
    payload: CatalogReviewRequest,
    reviewer: CatalogReviewer,
    db: DbSession,
) -> dict:
    """Change symptom publication state; only provisioned reviewers may act."""
    item = db.scalar(select(Symptom).where(Symptom.code == symptom_code))
    if item is None:
        raise HTTPException(status_code=404, detail="Symptom not found.")
    result = _apply_review_decision(item, payload, reviewer)
    db.commit()
    return result


@router.patch("/review/diseases/{disease_code}/symptoms/{symptom_code}")
def review_disease_symptom_link(
    disease_code: str,
    symptom_code: str,
    payload: CatalogReviewRequest,
    reviewer: CatalogReviewer,
    db: DbSession,
) -> dict:
    """Review a disease-symptom association using an authorized reviewer."""
    disease = db.scalar(select(Disease).where(Disease.code == disease_code))
    symptom = db.scalar(select(Symptom).where(Symptom.code == symptom_code))
    if disease is None or symptom is None:
        raise HTTPException(status_code=404, detail="Disease or symptom not found.")
    item = db.get(DiseaseSymptom, (disease.id, symptom.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Disease-symptom link not found.")
    result = _apply_review_decision(item, payload, reviewer)
    db.commit()
    return result

