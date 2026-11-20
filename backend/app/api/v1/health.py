"""Health-check endpoints for liveness and database readiness."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DbSession
from app.core.config import get_settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Check API liveness")
def health_check() -> dict[str, str]:
    """Return lightweight process status without requiring PostgreSQL."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/health/ready", summary="Check database readiness")
def readiness_check(db: DbSession) -> dict[str, str]:
    """Confirm the API can execute a trivial query against its database."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready.",
        ) from None
    return {"status": "ready", "database": "available"}
