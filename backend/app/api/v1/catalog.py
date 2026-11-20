"""Public catalog reads and authorized catalog review actions."""

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, literal, or_, select

from app.api.dependencies import CatalogReviewer, DbSession
from app.models.catalog import CatalogReviewEvent, Disease, DiseaseSymptom, Symptom
from app.models.catalog_reference import CatalogReference, CatalogReferenceEvent
from app.models.reviewer_scope import CatalogReviewerScope
from app.models.knowledge import MedicalReference
from app.schemas.catalog import (
    CatalogItemRead,
    CatalogListResponse,
    DiseaseSymptomItemRead,
    CatalogReviewRequest,
    CatalogReviewEventRead,
    CatalogReviewQueueItemRead,
)
from app.schemas.knowledge import (
    CatalogReferenceLinkRequest,
    CatalogReferenceRead,
    CatalogReferenceRemovalRequest,
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


@router.get("/review/workload")
def read_reviewer_workload(
    reviewer: CatalogReviewer,
    db: DbSession,
) -> dict:
    """Return scoped pending workload and the authenticated reviewer's own activity."""
    scope_filters = {
        "disease": (
            True if reviewer.role == "admin"
            else _reviewer_scope_exists(reviewer, "disease", Disease.code)
        ),
        "symptom": (
            True if reviewer.role == "admin"
            else _reviewer_scope_exists(reviewer, "symptom", Symptom.code)
        ),
        "disease_symptom": (
            True if reviewer.role == "admin"
            else _reviewer_scope_exists(
                reviewer,
                "disease_symptom",
                Disease.code + literal(":") + Symptom.code,
            )
        ),
    }
    models = {
        "disease": Disease,
        "symptom": Symptom,
        "disease_symptom": DiseaseSymptom,
    }

    pending_by_type: dict[str, int] = {}
    for target_type, model in models.items():
        pending_by_type[target_type] = int(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.review_status.in_(("draft", "in_review")),
                    scope_filters[target_type],
                )
            ) or 0
        )

    activity = select(CatalogReviewEvent)
    if reviewer.role != "admin":
        activity = activity.where(CatalogReviewEvent.reviewer_id == reviewer.id)

    total_decisions = int(
        db.scalar(select(func.count()).select_from(activity.subquery())) or 0
    )
    approved_decisions = int(
        db.scalar(
            select(func.count())
            .select_from(CatalogReviewEvent)
            .where(
                CatalogReviewEvent.new_status == "approved",
                *(
                    [CatalogReviewEvent.reviewer_id == reviewer.id]
                    if reviewer.role != "admin" else []
                ),
            )
        ) or 0
    )
    retired_decisions = int(
        db.scalar(
            select(func.count())
            .select_from(CatalogReviewEvent)
            .where(
                CatalogReviewEvent.new_status == "retired",
                *(
                    [CatalogReviewEvent.reviewer_id == reviewer.id]
                    if reviewer.role != "admin" else []
                ),
            )
        ) or 0
    )
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_decisions = int(
        db.scalar(
            select(func.count())
            .select_from(CatalogReviewEvent)
            .where(
                CatalogReviewEvent.created_at >= recent_cutoff,
                *(
                    [CatalogReviewEvent.reviewer_id == reviewer.id]
                    if reviewer.role != "admin" else []
                ),
            )
        ) or 0
    )

    active_scopes = []
    if reviewer.role != "admin":
        scope_rows = db.scalars(
            select(CatalogReviewerScope)
            .where(
                CatalogReviewerScope.reviewer_id == reviewer.id,
                CatalogReviewerScope.revoked_at.is_(None),
            )
            .order_by(
                CatalogReviewerScope.scope_type.asc(),
                CatalogReviewerScope.scope_key.asc(),
            )
        ).all()
        active_scopes = [
            {
                "scope_type": scope.scope_type,
                "scope_key": scope.scope_key,
                "granted_at": scope.granted_at,
            }
            for scope in scope_rows
        ]

    return {
        "pending_total": sum(pending_by_type.values()),
        "pending_by_type": pending_by_type,
        "is_unrestricted": reviewer.role == "admin",
        "assignments": active_scopes,
        "activity": {
            "total_decisions": total_decisions,
            "approved_decisions": approved_decisions,
            "retired_decisions": retired_decisions,
            "decisions_last_7_days": recent_decisions,
        },
    }


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
    q: str | None = Query(default=None, min_length=1, max_length=120),
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[CatalogReviewQueueItemRead]:
    """Return a stable, scope-filtered page of catalog entries for reviewers."""
    allowed_statuses = {"draft", "in_review", "approved", "retired"}
    if not statuses or any(value not in allowed_statuses for value in statuses):
        raise HTTPException(status_code=422, detail="Unsupported review status filter.")

    search = f"%{q.strip()}%" if q and q.strip() else None
    window = offset + limit + 1
    queue: list[CatalogReviewQueueItemRead] = []
    if target_type in (None, "disease"):
        statement = select(Disease).where(
            Disease.review_status.in_(statuses),
            True if reviewer.role == "admin" else _reviewer_scope_exists(
                reviewer, "disease", Disease.code
            ),
        )
        if search:
            statement = statement.where(
                or_(Disease.code.ilike(search), Disease.name.ilike(search),
                    Disease.description.ilike(search))
            )
        diseases = db.scalars(
            statement.order_by(Disease.created_at.asc(), Disease.code.asc())
            .limit(window)
        ).all()
        queue.extend(
            CatalogReviewQueueItemRead(
                target_type="disease", target_key=item.code, name=item.name,
                description=item.description, status=item.review_status,
                created_at=item.created_at,
            )
            for item in diseases
        )

    if target_type in (None, "symptom"):
        statement = select(Symptom).where(
            Symptom.review_status.in_(statuses),
            True if reviewer.role == "admin" else _reviewer_scope_exists(
                reviewer, "symptom", Symptom.code
            ),
        )
        if search:
            statement = statement.where(
                or_(Symptom.code.ilike(search), Symptom.name.ilike(search),
                    Symptom.description.ilike(search))
            )
        symptoms = db.scalars(
            statement.order_by(Symptom.created_at.asc(), Symptom.code.asc())
            .limit(window)
        ).all()
        queue.extend(
            CatalogReviewQueueItemRead(
                target_type="symptom", target_key=item.code, name=item.name,
                description=item.description, status=item.review_status,
                created_at=item.created_at,
            )
            for item in symptoms
        )

    if target_type in (None, "disease_symptom"):
        statement = (
            select(DiseaseSymptom, Disease, Symptom)
            .join(Disease, Disease.id == DiseaseSymptom.disease_id)
            .join(Symptom, Symptom.id == DiseaseSymptom.symptom_id)
            .where(
                DiseaseSymptom.review_status.in_(statuses),
                True if reviewer.role == "admin" else _reviewer_scope_exists(
                    reviewer, "disease_symptom",
                    Disease.code + literal(":") + Symptom.code,
                ),
            )
        )
        if search:
            statement = statement.where(
                or_(
                    (Disease.code + literal(":") + Symptom.code).ilike(search),
                    Disease.name.ilike(search),
                    Symptom.name.ilike(search),
                )
            )
        links = db.execute(
            statement.order_by(Disease.code.asc(), Symptom.code.asc())
            .limit(window)
        ).all()
        queue.extend(
            CatalogReviewQueueItemRead(
                target_type="disease_symptom",
                target_key=f"{disease.code}:{symptom.code}",
                name=f"{disease.name} — {symptom.name}",
                description=None, status=link.review_status, created_at=None,
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
    return queue[offset : offset + limit + 1]


@router.get("/review/queue/entry")
def read_pending_catalog_review_entry(
    reviewer: CatalogReviewer,
    db: DbSession,
    target_type: str = Query(pattern="^(disease|symptom|disease_symptom)$"),
    target_key: str = Query(min_length=1, max_length=200),
) -> dict:
    """Return an authorized pending catalog record for evidence-aware inspection."""
    if target_type == "disease":
        item = db.scalar(select(Disease).where(Disease.code == target_key))
        if item is None:
            raise HTTPException(status_code=404, detail="Pending catalog entry not found.")
        _require_item_scope(reviewer, db, "disease", item.code)
        if item.review_status not in ("draft", "in_review"):
            raise HTTPException(status_code=404, detail="Pending catalog entry not found.")
        entry = {
            "target_type": "disease",
            "target_key": item.code,
            "name": item.name,
            "description": item.description,
            "status": item.review_status,
            "is_active": item.is_active,
            "created_at": item.created_at,
            "reviewed_by": item.reviewed_by,
            "reviewed_at": item.reviewed_at,
            "related_entries": [],
            "relevance_weight": None,
        }
    elif target_type == "symptom":
        item = db.scalar(select(Symptom).where(Symptom.code == target_key))
        if item is None:
            raise HTTPException(status_code=404, detail="Pending catalog entry not found.")
        _require_item_scope(reviewer, db, "symptom", item.code)
        if item.review_status not in ("draft", "in_review"):
            raise HTTPException(status_code=404, detail="Pending catalog entry not found.")
        entry = {
            "target_type": "symptom",
            "target_key": item.code,
            "name": item.name,
            "description": item.description,
            "status": item.review_status,
            "is_active": item.is_active,
            "created_at": item.created_at,
            "reviewed_by": item.reviewed_by,
            "reviewed_at": item.reviewed_at,
            "related_entries": [],
            "relevance_weight": None,
        }
    else:
        disease_code, separator, symptom_code = target_key.partition(":")
        if not separator or not disease_code or not symptom_code or ":" in symptom_code:
            raise HTTPException(status_code=404, detail="Pending catalog entry not found.")
        row = db.execute(
            select(DiseaseSymptom, Disease, Symptom)
            .join(Disease, Disease.id == DiseaseSymptom.disease_id)
            .join(Symptom, Symptom.id == DiseaseSymptom.symptom_id)
            .where(Disease.code == disease_code, Symptom.code == symptom_code)
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Pending catalog entry not found.")
        link, disease, symptom = row
        _require_item_scope(reviewer, db, "disease_symptom", target_key)
        if link.review_status not in ("draft", "in_review"):
            raise HTTPException(status_code=404, detail="Pending catalog entry not found.")
        entry = {
            "target_type": "disease_symptom",
            "target_key": target_key,
            "name": f"{disease.name} — {symptom.name}",
            "description": None,
            "status": link.review_status,
            "is_active": disease.is_active and symptom.is_active,
            "created_at": None,
            "reviewed_by": link.reviewed_by,
            "reviewed_at": link.reviewed_at,
            "related_entries": [
                {"target_type": "disease", "target_key": disease.code, "name": disease.name,
                 "status": disease.review_status},
                {"target_type": "symptom", "target_key": symptom.code, "name": symptom.name,
                 "status": symptom.review_status},
            ],
            "relevance_weight": link.relevance_weight,
        }

    reference_rows = db.execute(
        select(CatalogReference, MedicalReference)
        .join(MedicalReference, MedicalReference.id == CatalogReference.reference_id)
        .where(
            CatalogReference.target_type == target_type,
            CatalogReference.target_key == target_key,
            CatalogReference.removed_at.is_(None),
        )
        .order_by(CatalogReference.created_at.desc(), CatalogReference.id.desc())
    ).all()
    references = [
        CatalogReferenceRead(
            id=link.id,
            reference_id=source.id,
            title=source.title,
            publisher=source.publisher,
            url=source.url,
            evidence_type=source.evidence_type,
            version=source.version,
            published_on=source.published_on,
            accessed_on=source.accessed_on,
            review_status=source.review_status,
            reviewed_by=source.reviewed_by,
            reviewed_at=source.reviewed_at,
            next_review_due=source.next_review_due,
            link_reason=link.link_reason,
            linked_by=link.linked_by,
            linked_at=link.created_at,
        )
        for link, source in reference_rows
    ]
    return {
        "entry": entry,
        "evidence": {
            "references": [item.model_dump(mode="json") for item in references],
            "reference_support": "available",
            "message": (
                "Attached source records are provenance metadata only. Check each "
                "source's review status and currency; an attachment is not clinical validation."
            ) if references else (
                "No source references are attached to this entry yet. Reviewers should "
                "seek appropriate authoritative sources before making a decision."
            ),
        },
    }


def _pending_target_for_reference(db, target_type: str, target_key: str):
    """Resolve a pending catalog target; never create links to unknown or finalized rows."""
    if target_type == "disease":
        item = db.scalar(select(Disease).where(Disease.code == target_key))
        if item is not None and item.review_status in ("draft", "in_review"):
            return item
    elif target_type == "symptom":
        item = db.scalar(select(Symptom).where(Symptom.code == target_key))
        if item is not None and item.review_status in ("draft", "in_review"):
            return item
    elif target_type == "disease_symptom":
        disease_code, separator, symptom_code = target_key.partition(":")
        if separator and disease_code and symptom_code and ":" not in symptom_code:
            row = db.execute(
                select(DiseaseSymptom, Disease, Symptom)
                .join(Disease, Disease.id == DiseaseSymptom.disease_id)
                .join(Symptom, Symptom.id == DiseaseSymptom.symptom_id)
                .where(Disease.code == disease_code, Symptom.code == symptom_code)
            ).first()
            if row is not None and row[0].review_status in ("draft", "in_review"):
                return row[0]
    raise HTTPException(status_code=404, detail="Pending catalog entry not found.")


@router.get("/review/queue/entry/references")
def list_pending_catalog_references(
    reviewer: CatalogReviewer,
    db: DbSession,
    target_type: str = Query(pattern="^(disease|symptom|disease_symptom)$"),
    target_key: str = Query(min_length=1, max_length=200),
) -> list[dict]:
    """List attached references only within the caller's active review scope."""
    _pending_target_for_reference(db, target_type, target_key)
    _require_item_scope(reviewer, db, target_type, target_key)
    rows = db.execute(
        select(CatalogReference, MedicalReference)
        .join(MedicalReference, MedicalReference.id == CatalogReference.reference_id)
        .where(
            CatalogReference.target_type == target_type,
            CatalogReference.target_key == target_key,
            CatalogReference.removed_at.is_(None),
        )
        .order_by(CatalogReference.created_at.desc())
    ).all()
    return [
        {
            "id": str(link.id),
            "reference_id": str(source.id),
            "title": source.title,
            "publisher": source.publisher,
            "url": source.url,
            "evidence_type": source.evidence_type,
            "version": source.version,
            "published_on": source.published_on,
            "accessed_on": source.accessed_on,
            "review_status": source.review_status,
            "reviewed_by": source.reviewed_by,
            "reviewed_at": source.reviewed_at,
            "next_review_due": source.next_review_due,
            "link_reason": link.link_reason,
            "linked_by": str(link.linked_by),
            "linked_at": link.created_at,
        }
        for link, source in rows
    ]


@router.post("/review/queue/entry/references", status_code=201)
def attach_pending_catalog_reference(
    payload: CatalogReferenceLinkRequest,
    reviewer: CatalogReviewer,
    db: DbSession,
) -> dict:
    """Attach an existing source to an assigned pending entry with an audit event."""
    _pending_target_for_reference(db, payload.target_type, payload.target_key)
    _require_item_scope(reviewer, db, payload.target_type, payload.target_key)
    source = db.get(MedicalReference, payload.reference_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Medical reference not found.")

    link = db.scalar(
        select(CatalogReference).where(
            CatalogReference.target_type == payload.target_type,
            CatalogReference.target_key == payload.target_key,
            CatalogReference.reference_id == payload.reference_id,
        ).with_for_update()
    )
    if link is not None and link.removed_at is None:
        raise HTTPException(status_code=409, detail="This source is already attached.")
    if link is None:
        link = CatalogReference(
            target_type=payload.target_type,
            target_key=payload.target_key,
            reference_id=payload.reference_id,
            linked_by=reviewer.id,
            link_reason=payload.reason,
        )
        db.add(link)
        db.flush()
    else:
        link.linked_by = reviewer.id
        link.link_reason = payload.reason
        link.created_at = datetime.now(timezone.utc)
        link.removed_by = None
        link.removed_at = None
        link.removal_reason = None
    db.add(CatalogReferenceEvent(
        catalog_reference_id=link.id,
        reference_id=source.id,
        target_type=payload.target_type,
        target_key=payload.target_key,
        event_type="linked",
        reason=payload.reason,
        actor_id=reviewer.id,
    ))
    db.commit()
    return {"id": str(link.id), "reference_id": str(source.id), "status": "linked"}


@router.post("/review/queue/entry/references/{link_id}/remove")
def remove_pending_catalog_reference(
    link_id: UUID,
    payload: CatalogReferenceRemovalRequest,
    reviewer: CatalogReviewer,
    db: DbSession,
) -> dict:
    """Soft-remove a source link and append a non-destructive audit event."""
    link = db.scalar(
        select(CatalogReference).where(CatalogReference.id == link_id).with_for_update()
    )
    if link is None or link.removed_at is not None:
        raise HTTPException(status_code=404, detail="Active catalog source link not found.")
    _pending_target_for_reference(db, link.target_type, link.target_key)
    _require_item_scope(reviewer, db, link.target_type, link.target_key)
    link.removed_by = reviewer.id
    link.removed_at = datetime.now(timezone.utc)
    link.removal_reason = payload.reason
    db.add(CatalogReferenceEvent(
        catalog_reference_id=link.id,
        reference_id=link.reference_id,
        target_type=link.target_type,
        target_key=link.target_key,
        event_type="removed",
        reason=payload.reason,
        actor_id=reviewer.id,
    ))
    db.commit()
    return {"id": str(link.id), "status": "removed"}


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
    q: str | None = Query(default=None, min_length=1, max_length=120),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[CatalogReviewEventRead]:
    """Return filterable append-only review history to authorized reviewers."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to.")

    statement = select(CatalogReviewEvent)
    if reviewer.role != "admin":
        statement = statement.where(CatalogReviewEvent.reviewer_id == reviewer.id)
    if target_type:
        statement = statement.where(CatalogReviewEvent.target_type == target_type)
    if target_key:
        statement = statement.where(CatalogReviewEvent.target_key == target_key)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                CatalogReviewEvent.target_key.ilike(pattern),
                CatalogReviewEvent.reason.ilike(pattern),
            )
        )
    if date_from:
        statement = statement.where(
            CatalogReviewEvent.created_at >= datetime.combine(
                date_from, time.min, tzinfo=timezone.utc
            )
        )
    if date_to:
        statement = statement.where(
            CatalogReviewEvent.created_at < datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=timezone.utc
            )
        )
    events = db.scalars(
        statement.order_by(
            CatalogReviewEvent.created_at.desc(),
            CatalogReviewEvent.id.desc(),
        ).limit(limit)
    ).all()
    return [CatalogReviewEventRead.model_validate(event) for event in events]


@router.get("/review/history/{event_id}/entry")
def read_reviewed_catalog_entry(
    event_id: UUID,
    reviewer: CatalogReviewer,
    db: DbSession,
) -> dict:
    """Read the catalog entry attached to an event visible to this reviewer."""
    event = db.scalar(
        select(CatalogReviewEvent).where(CatalogReviewEvent.id == event_id)
    )
    if event is None or (
        reviewer.role != "admin" and event.reviewer_id != reviewer.id
    ):
        raise HTTPException(status_code=404, detail="Review history entry not found.")

    if event.target_type == "disease":
        item = db.scalar(select(Disease).where(Disease.code == event.target_key))
        if item is None:
            raise HTTPException(status_code=404, detail="Catalog entry no longer exists.")
        entry = {
            "target_type": "disease",
            "target_key": item.code,
            "name": item.name,
            "description": item.description,
            "status": item.review_status,
            "created_at": item.created_at,
            "relevance_weight": None,
        }
    elif event.target_type == "symptom":
        item = db.scalar(select(Symptom).where(Symptom.code == event.target_key))
        if item is None:
            raise HTTPException(status_code=404, detail="Catalog entry no longer exists.")
        entry = {
            "target_type": "symptom",
            "target_key": item.code,
            "name": item.name,
            "description": item.description,
            "status": item.review_status,
            "created_at": item.created_at,
            "relevance_weight": None,
        }
    else:
        disease_code, separator, symptom_code = event.target_key.partition(":")
        if not separator or not disease_code or not symptom_code:
            raise HTTPException(status_code=404, detail="Catalog entry no longer exists.")
        row = db.execute(
            select(DiseaseSymptom, Disease, Symptom)
            .join(Disease, Disease.id == DiseaseSymptom.disease_id)
            .join(Symptom, Symptom.id == DiseaseSymptom.symptom_id)
            .where(Disease.code == disease_code, Symptom.code == symptom_code)
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Catalog entry no longer exists.")
        link, disease, symptom = row
        entry = {
            "target_type": "disease_symptom",
            "target_key": event.target_key,
            "name": f"{disease.name} — {symptom.name}",
            "description": None,
            "status": link.review_status,
            "created_at": None,
            "relevance_weight": link.relevance_weight,
        }

    return {
        "event": CatalogReviewEventRead.model_validate(event),
        "entry": entry,
    }

