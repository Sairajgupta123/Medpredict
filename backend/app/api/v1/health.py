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



@router.get("/models/status", summary="Check research model configuration")
def research_model_status() -> dict[str, object]:
    """Report model-path configuration without loading or executing any artifact.

    A configured path does not mean that an artifact exists, is trusted, or is
    usable. Model loading and inference remain disabled in the API.
    """
    from pathlib import Path

    settings = get_settings()

    def capability(path_value: str | None) -> dict[str, str | bool]:
        if path_value is None or not path_value.strip():
            return {
                "status": "not_configured",
                "configured": False,
                "loaded": False,
                "inference_enabled": False,
            }
        candidate = Path(path_value)
        if not candidate.is_absolute():
            return {
                "status": "invalid_configuration",
                "configured": True,
                "loaded": False,
                "inference_enabled": False,
            }
        return {
            "status": "configured_not_loaded",
            "configured": True,
            "loaded": False,
            "inference_enabled": False,
        }

    return {
        "skin_image": capability(settings.skin_research_checkpoint_path),
        "symptom_text": capability(settings.text_research_artifact_path),
        "research_only": True,
        "clinical_diagnosis_enabled": False,
    }
