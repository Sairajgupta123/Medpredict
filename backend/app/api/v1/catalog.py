"""Public catalog reads and authorized catalog review actions."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, literal, or_, select

from app.api.dependencies import CatalogReviewer, DbSession
from app.models.catalog import CatalogReviewEvent, Disease, DiseaseSymptom, Symptom
from app.models.reviewer_scope import CatalogReviewerScope
from app.schemas.catalog import (
    CatalogItemRead,
    CatalogListResponse,
    DiseaseSymptomItemRead,
    CatalogReviewRequest,
    CatalogReviewEventRead,
    CatalogReviewQueueItemRead,
)

router = APIRouter(prefix="/catalog", tags=["Medical Catalog"])


def _reviewer_scope_exists(reviewer, target_type: str, target_key_expression):
    """Build a SQL predicate for an active matching reviewer scope."""
    return select(CatalogReviewerScope.id).where(
        CatalogReviewerScope.reviewer_id == reviewer.id,
        CatalogReviewerScope.scope_type == target_type,
        CatalogReviewerScope.revoked_at.is_(None),
        or_(
            CatalogReviewerScope.scope_key.is_(None),
            CatalogReviewerScope.scope_key == target_key_expression,
        ),
    ).exists()


def _require_item_scope(reviewer, db, target_type: str, target_key: str) -> None:
    """Enforce exact or type-wide grants before a reviewer can change an item."""
    if reviewer.role == "admin":
        return
    allowed = db.scalar(
        select(CatalogReviewerScope.id).where(
            CatalogReviewerScope.reviewer_id == reviewer.id,
            CatalogReviewerScope.scope_type == target_type,
            CatalogReviewerScope.revoked_at.is_(None),
            or_(
                CatalogReviewerScope.scope_key.is_(None),
                CatalogReviewerScope.scope_key == target_key,
            ),
        ).limit(1)
    )
    if allowed is None:
        raise HTTPException(
            status_code=403,
            detail="Your reviewer account is not assigned to this catalog scope.",
        )



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

def _apply_review_decision(
    item,
    payload: CatalogReviewRequest,
    reviewer,
    db,
    target_type: str,
    target_key: str,
) -> dict:
    """Apply a decision and append an immutable audit event in the same transaction."""
    previous_status = item.review_status
    if previous_status != payload.expected_status:
        raise HTTPException(
            status_code=409,
            detail=(
                "This catalog entry changed after you opened it. "
                "Refresh the review queue before submitting another decision."
            ),
        )
    item.review_status = payload.status
    if payload.status == "approved":
        item.reviewed_by = str(reviewer.id)
        item.reviewed_at = datetime.now(timezone.utc)
    else:
        item.reviewed_by = None
        item.reviewed_at = None

    db.add(
        CatalogReviewEvent(
            target_type=target_type,
            target_key=target_key,
            previous_status=previous_status,
            new_status=payload.status,
            reason=payload.reason.strip(),
            reviewer_id=reviewer.id,
        )
    )
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
    item = db.scalar(select(Disease).where(Disease.code == disease_code).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="Disease not found.")
    _require_item_scope(reviewer, db, "disease", disease_code)
    result = _apply_review_decision(item, payload, reviewer, db, "disease", disease_code)
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
    item = db.scalar(select(Symptom).where(Symptom.code == symptom_code).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="Symptom not found.")
    _require_item_scope(reviewer, db, "symptom", symptom_code)
    result = _apply_review_decision(item, payload, reviewer, db, "symptom", symptom_code)
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
    item = db.scalar(
        select(DiseaseSymptom)
        .where(
            DiseaseSymptom.disease_id == disease.id,
            DiseaseSymptom.symptom_id == symptom.id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Disease-symptom link not found.")
    _require_item_scope(
        reviewer, db, "disease_symptom", f"{disease_code}:{symptom_code}"
    )
    result = _apply_review_decision(
        item, payload, reviewer, db, "disease_symptom",
        f"{disease_code}:{symptom_code}"
    )
    db.commit()
    return result

@router.get(
    "/review/queue",
    response_model=list[CatalogReviewQueueItemRead],
)
def list_catalog_review_queue(
    reviewer: CatalogReviewer,
    db: DbSession,
    target_type: str | None = Query(
        default=None, pattern="^(disease|symptom|disease_symptom)$"
    ),
    statuses: list[str] = Query(default=["draft", "in_review"], alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[CatalogReviewQueueItemRead]:
    """List pending catalog entries for authorized reviewers only."""
    allowed_statuses = {"draft", "in_review", "approved", "retired"}
    if not statuses or any(value not in allowed_statuses for value in statuses):
        raise HTTPException(status_code=422, detail="Unsupported review status filter.")

    queue: list[CatalogReviewQueueItemRead] = []
    if target_type in (None, "disease"):
        diseases = db.scalars(
            select(Disease)
            .where(
                Disease.review_status.in_(statuses),
                True if reviewer.role == "admin" else _reviewer_scope_exists(
                    reviewer, "disease", Disease.code
                ),
            )
            .order_by(Disease.created_at.asc(), Disease.code.asc())
            .limit(limit)
        ).all()
        queue.extend(
            CatalogReviewQueueItemRead(
                target_type="disease",
                target_key=item.code,
                name=item.name,
                description=item.description,
                status=item.review_status,
                created_at=item.created_at,
            )
            for item in diseases
        )

    if target_type in (None, "symptom"):
        symptoms = db.scalars(
            select(Symptom)
            .where(
                Symptom.review_status.in_(statuses),
                True if reviewer.role == "admin" else _reviewer_scope_exists(
                    reviewer, "symptom", Symptom.code
                ),
            )
            .order_by(Symptom.created_at.asc(), Symptom.code.asc())
            .limit(limit)
        ).all()
        queue.extend(
            CatalogReviewQueueItemRead(
                target_type="symptom",
                target_key=item.code,
                name=item.name,
                description=item.description,
                status=item.review_status,
                created_at=item.created_at,
            )
            for item in symptoms
        )

    if target_type in (None, "disease_symptom"):
        links = db.execute(
            select(DiseaseSymptom, Disease, Symptom)
            .join(Disease, Disease.id == DiseaseSymptom.disease_id)
            .join(Symptom, Symptom.id == DiseaseSymptom.symptom_id)
            .where(
                DiseaseSymptom.review_status.in_(statuses),
                True if reviewer.role == "admin" else _reviewer_scope_exists(
                    reviewer,
                    "disease_symptom",
                    Disease.code + literal(":") + Symptom.code,
                ),
            )
            .order_by(Disease.code.asc(), Symptom.code.asc())
            .limit(limit)
        ).all()
        queue.extend(
            CatalogReviewQueueItemRead(
                target_type="disease_symptom",
                target_key=f"{disease.code}:{symptom.code}",
                name=f"{disease.name} — {symptom.name}",
                description=None,
                status=link.review_status,
                created_at=None,
            )
            for link, disease, symptom in links
        )

    queue.sort(
        key=lambda item: (
            item.created_at is None,
            item.created_at.isoformat() if item.created_at else "",
            item.target_type,
            item.target_key,
        )
    )
    return queue[:limit]


@router.get(
    "/review/history",
    response_model=list[CatalogReviewEventRead],
)
def list_catalog_review_history(
    reviewer: CatalogReviewer,
    db: DbSession,
    target_type: str | None = Query(
        default=None, pattern="^(disease|symptom|disease_symptom)$"
    ),
    target_key: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[CatalogReviewEventRead]:
    """Return append-only review history to authorized catalog reviewers."""
    statement = select(CatalogReviewEvent)
    if target_type:
        statement = statement.where(CatalogReviewEvent.target_type == target_type)
    if target_key:
        statement = statement.where(CatalogReviewEvent.target_key == target_key)
    events = db.scalars(
        statement.order_by(
            CatalogReviewEvent.created_at.desc(),
            CatalogReviewEvent.id.desc(),
        ).limit(limit)
    ).all()
    return [CatalogReviewEventRead.model_validate(event) for event in events]

