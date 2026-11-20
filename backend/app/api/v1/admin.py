"""Administrator-only operational governance overview."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.dependencies import Administrator, DbSession
from app.models.catalog import CatalogReviewEvent, Disease, DiseaseSymptom, Symptom
from app.models.user import RoleProvisioningEvent, User
from app.models.reviewer_scope import CatalogReviewerScope, CatalogReviewerScopeEvent
from app.models.knowledge import MedicalReference, MedicalReferenceEvent
from app.schemas.knowledge import (
    MedicalReferenceCreate,
    MedicalReferenceRead,
    MedicalReferenceReviewRequest,
)
from app.schemas.admin import (
    ReviewerScopeCreate,
    ReviewerScopeEventRead,
    ReviewerScopeRead,
    ReviewerScopeRevoke,
)

router = APIRouter(prefix="/admin", tags=["Administration"])


def _status_counts(db: DbSession, model) -> dict[str, int]:
    """Count records by review lifecycle state without exposing clinical content."""
    rows = db.execute(
        select(model.review_status, func.count())
        .group_by(model.review_status)
    ).all()
    return {status: count for status, count in rows}


@router.get("/governance")
def read_governance_overview(
    administrator: Administrator,
    db: DbSession,
    history_limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    """Return aggregate governance metrics and recent role-provisioning events."""
    role_rows = db.execute(
        select(User.role, User.is_active, func.count())
        .group_by(User.role, User.is_active)
    ).all()
    accounts = {
        role: {"active": 0, "inactive": 0}
        for role in ("patient", "reviewer", "admin")
    }
    for role, is_active, count in role_rows:
        accounts.setdefault(role, {"active": 0, "inactive": 0})[
            "active" if is_active else "inactive"
        ] = count

    provisioning_events = db.scalars(
        select(RoleProvisioningEvent)
        .order_by(
            RoleProvisioningEvent.created_at.desc(),
            RoleProvisioningEvent.id.desc(),
        )
        .limit(history_limit)
    ).all()

    return {
        "accounts": accounts,
        "catalog": {
            "diseases": _status_counts(db, Disease),
            "symptoms": _status_counts(db, Symptom),
            "disease_symptom_links": _status_counts(db, DiseaseSymptom),
        },
        "recent_role_changes": [
            {
                "id": event.id,
                "target_user_id": event.target_user_id,
                "previous_role": event.previous_role,
                "new_role": event.new_role,
                "operator_identity": event.operator_identity,
                "reason": event.reason,
                "created_at": event.created_at,
            }
            for event in provisioning_events
        ],
    }

def _scope_key_filter(scope_type: str, scope_key: str | None):
    statement = select(CatalogReviewerScope).where(
        CatalogReviewerScope.scope_type == scope_type
    )
    if scope_key is None:
        return statement.where(CatalogReviewerScope.scope_key.is_(None))
    return statement.where(CatalogReviewerScope.scope_key == scope_key)


def _validate_scope_target(db: DbSession, scope_type: str, scope_key: str | None) -> None:
    """Ensure exact assignments refer to existing catalog keys."""
    if scope_key is None:
        return
    if scope_type == "disease":
        exists = db.scalar(select(Disease.id).where(Disease.code == scope_key))
    elif scope_type == "symptom":
        exists = db.scalar(select(Symptom.id).where(Symptom.code == scope_key))
    else:
        parts = scope_key.split(":")
        if len(parts) != 2 or not all(parts):
            raise HTTPException(
                status_code=422,
                detail="Disease-symptom scopes must use DISEASE_CODE:SYMPTOM_CODE.",
            )
        disease_id = db.scalar(select(Disease.id).where(Disease.code == parts[0]))
        symptom_id = db.scalar(select(Symptom.id).where(Symptom.code == parts[1]))
        exists = disease_id and symptom_id
    if not exists:
        raise HTTPException(status_code=404, detail="The requested catalog scope was not found.")


@router.get("/reviewers")
def list_eligible_reviewers(
    administrator: Administrator,
    db: DbSession,
) -> list[dict]:
    """List active, verified reviewer accounts for scoped assignment."""
    reviewers = db.scalars(
        select(User)
        .where(
            User.role == "reviewer",
            User.is_active.is_(True),
            User.email_verified.is_(True),
        )
        .order_by(User.email.asc())
    ).all()
    return [
        {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
        }
        for user in reviewers
    ]


@router.get("/reviewer-scopes", response_model=list[ReviewerScopeRead])
def list_reviewer_scopes(
    administrator: Administrator,
    db: DbSession,
    include_revoked: bool = Query(default=True),
) -> list[dict]:
    """List current and historical reviewer scope grants for administrators."""
    statement = (
        select(CatalogReviewerScope, User.email)
        .join(User, User.id == CatalogReviewerScope.reviewer_id)
        .order_by(CatalogReviewerScope.granted_at.desc(), CatalogReviewerScope.id.desc())
    )
    if not include_revoked:
        statement = statement.where(CatalogReviewerScope.revoked_at.is_(None))
    rows = db.execute(statement).all()
    return [
        {
            **ReviewerScopeRead.model_validate(scope).model_dump(),
            "reviewer_email": email,
        }
        for scope, email in rows
    ]


@router.post("/reviewer-scopes", response_model=ReviewerScopeRead, status_code=201)
def grant_reviewer_scope(
    payload: ReviewerScopeCreate,
    administrator: Administrator,
    db: DbSession,
) -> dict:
    """Grant a reviewer an exact catalog item or whole catalog-type scope."""
    target = db.scalar(
        select(User)
        .where(User.id == payload.reviewer_id)
        .with_for_update()
    )
    if (
        target is None
        or not target.is_active
        or not target.email_verified
        or target.role != "reviewer"
    ):
        raise HTTPException(
            status_code=404,
            detail="An active reviewer account is required for scope assignment.",
        )
    _validate_scope_target(db, payload.scope_type, payload.scope_key)

    existing = db.scalar(
        _scope_key_filter(payload.scope_type, payload.scope_key).where(
            CatalogReviewerScope.reviewer_id == target.id
        )
    )
    if existing is not None and existing.revoked_at is None:
        raise HTTPException(status_code=409, detail="This reviewer scope is already active.")

    if existing is None:
        scope = CatalogReviewerScope(
            reviewer_id=target.id,
            scope_type=payload.scope_type,
            scope_key=payload.scope_key,
            granted_by=administrator.id,
            grant_reason=payload.reason,
        )
        db.add(scope)
        db.flush()
    else:
        scope = existing
        scope.granted_by = administrator.id
        scope.grant_reason = payload.reason
        scope.granted_at = datetime.now(timezone.utc)
        scope.revoked_by = None
        scope.revoked_at = None
        scope.revoke_reason = None

    db.add(
        CatalogReviewerScopeEvent(
            scope_id=scope.id,
            reviewer_id=target.id,
            event_type="granted",
            scope_type=payload.scope_type,
            scope_key=payload.scope_key,
            operator_id=administrator.id,
            reason=payload.reason,
        )
    )
    db.commit()
    db.refresh(scope)
    return {
        **ReviewerScopeRead.model_validate(scope).model_dump(),
        "reviewer_email": target.email,
    }


@router.post(
    "/reviewer-scopes/{scope_id}/revoke",
    response_model=ReviewerScopeRead,
)
def revoke_reviewer_scope(
    scope_id: UUID,
    payload: ReviewerScopeRevoke,
    administrator: Administrator,
    db: DbSession,
) -> dict:
    """Revoke an active scope and append an immutable audit event atomically."""
    scope = db.scalar(
        select(CatalogReviewerScope)
        .where(CatalogReviewerScope.id == scope_id)
        .with_for_update()
    )
    if scope is None:
        raise HTTPException(status_code=404, detail="Reviewer scope not found.")
    if scope.revoked_at is not None:
        raise HTTPException(status_code=409, detail="This reviewer scope is already revoked.")

    target = db.get(User, scope.reviewer_id)
    scope.revoked_by = administrator.id
    scope.revoked_at = datetime.now(timezone.utc)
    scope.revoke_reason = payload.reason
    db.add(
        CatalogReviewerScopeEvent(
            scope_id=scope.id,
            reviewer_id=scope.reviewer_id,
            event_type="revoked",
            scope_type=scope.scope_type,
            scope_key=scope.scope_key,
            operator_id=administrator.id,
            reason=payload.reason,
        )
    )
    db.commit()
    db.refresh(scope)
    return {
        **ReviewerScopeRead.model_validate(scope).model_dump(),
        "reviewer_email": target.email if target else "",
    }


@router.get(
    "/reviewer-scopes/history",
    response_model=list[ReviewerScopeEventRead],
)
def list_reviewer_scope_history(
    administrator: Administrator,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ReviewerScopeEventRead]:
    """Return append-only scope grant/revocation events to administrators."""
    events = db.scalars(
        select(CatalogReviewerScopeEvent)
        .order_by(
            CatalogReviewerScopeEvent.created_at.desc(),
            CatalogReviewerScopeEvent.id.desc(),
        )
        .limit(limit)
    ).all()
    return [ReviewerScopeEventRead.model_validate(event) for event in events]



@router.get("/medical-references", response_model=list[MedicalReferenceRead])
def list_medical_references(
    administrator: Administrator,
    db: DbSession,
    q: str | None = Query(default=None, max_length=120),
    review_status: str | None = Query(
        default=None, pattern="^(draft|in_review|approved|retired)$"
    ),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[MedicalReference]:
    """List source records for administrator governance and maintenance."""
    statement = select(MedicalReference)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            MedicalReference.title.ilike(pattern)
            | MedicalReference.publisher.ilike(pattern)
            | MedicalReference.evidence_type.ilike(pattern)
        )
    if review_status:
        statement = statement.where(MedicalReference.review_status == review_status)
    return list(db.scalars(
        statement.order_by(MedicalReference.created_at.desc()).limit(limit)
    ).all())


@router.post(
    "/medical-references",
    response_model=MedicalReferenceRead,
    status_code=201,
)
def create_medical_reference(
    payload: MedicalReferenceCreate,
    administrator: Administrator,
    db: DbSession,
) -> MedicalReference:
    """Create a source record as a draft; creation never implies source approval."""
    duplicate = db.scalar(
        select(MedicalReference.id).where(
            MedicalReference.url == str(payload.url),
            MedicalReference.version == payload.version,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail="A source with this URL and version already exists.",
        )
    source = MedicalReference(
        title=payload.title,
        publisher=payload.publisher,
        url=str(payload.url),
        evidence_type=payload.evidence_type,
        version=payload.version,
        published_on=payload.published_on,
        accessed_on=payload.accessed_on,
        license_name=payload.license_name,
        content_sha256=payload.content_sha256.lower() if payload.content_sha256 else None,
        next_review_due=payload.next_review_due,
        review_status="draft",
    )
    db.add(source)
    db.flush()
    db.add(MedicalReferenceEvent(
        reference_id=source.id,
        event_type="created",
        previous_status=None,
        new_status="draft",
        reason=payload.reason,
        actor_id=administrator.id,
    ))
    db.commit()
    db.refresh(source)
    return source


@router.post(
    "/medical-references/{reference_id}/review",
    response_model=MedicalReferenceRead,
)
def review_medical_reference(
    reference_id: UUID,
    payload: MedicalReferenceReviewRequest,
    administrator: Administrator,
    db: DbSession,
) -> MedicalReference:
    """Change a source lifecycle state with optimistic locking and immutable audit."""
    source = db.scalar(
        select(MedicalReference)
        .where(MedicalReference.id == reference_id)
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Medical reference not found.")
    if source.review_status != payload.expected_status:
        raise HTTPException(
            status_code=409,
            detail="This source changed after it was opened. Refresh before reviewing again.",
        )
    previous_status = source.review_status
    source.review_status = payload.status
    if payload.status == "approved":
        source.reviewed_by = str(administrator.id)
        source.reviewed_at = datetime.now(timezone.utc)
    else:
        source.reviewed_by = None
        source.reviewed_at = None
    db.add(MedicalReferenceEvent(
        reference_id=source.id,
        event_type="status_changed",
        previous_status=previous_status,
        new_status=payload.status,
        reason=payload.reason,
        actor_id=administrator.id,
    ))
    db.commit()
    db.refresh(source)
    return source


@router.get("/medical-references/{reference_id}/history")
def read_medical_reference_history(
    reference_id: UUID,
    administrator: Administrator,
    db: DbSession,
) -> list[dict]:
    """Return immutable registration and review events for one source record."""
    if db.get(MedicalReference, reference_id) is None:
        raise HTTPException(status_code=404, detail="Medical reference not found.")
    events = db.scalars(
        select(MedicalReferenceEvent)
        .where(MedicalReferenceEvent.reference_id == reference_id)
        .order_by(MedicalReferenceEvent.created_at.desc(), MedicalReferenceEvent.id.desc())
    ).all()
    return [
        {
            "id": str(event.id),
            "reference_id": str(event.reference_id),
            "event_type": event.event_type,
            "previous_status": event.previous_status,
            "new_status": event.new_status,
            "reason": event.reason,
            "actor_id": str(event.actor_id),
            "created_at": event.created_at,
        }
        for event in events
    ]
