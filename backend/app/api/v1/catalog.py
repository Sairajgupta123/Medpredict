"""Read-only endpoints for curated diseases and symptoms."""

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.dependencies import DbSession
from app.models.catalog import Disease, Symptom
from app.schemas.catalog import CatalogItemRead, CatalogListResponse

router = APIRouter(prefix="/catalog", tags=["Medical Catalog"])


def _list_catalog_items(
    db: DbSession,
    model: type[Disease] | type[Symptom],
    query: str | None,
    limit: int,
    offset: int,
) -> CatalogListResponse:
    """Return active entries, requiring explicit approval for symptoms."""
    statement = select(model).where(model.is_active.is_(True))
    count_statement = select(func.count()).select_from(model).where(
        model.is_active.is_(True)
    )

    # The packaged symptom phrase taxonomy is research-only. The database-backed
    # symptom catalogue is a separate publication channel and must never expose
    # drafts, in-review records, or retired entries.
    if model is Symptom:
        statement = statement.where(Symptom.review_status == "approved")
        count_statement = count_statement.where(Symptom.review_status == "approved")

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
    """Browse active supported conditions in the curated catalog."""
    return _list_catalog_items(db, Disease, q, limit, offset)
