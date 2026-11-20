"""Administrator-only operational governance overview."""

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.dependencies import Administrator, DbSession
from app.models.catalog import CatalogReviewEvent, Disease, DiseaseSymptom, Symptom
from app.models.user import RoleProvisioningEvent, User

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
