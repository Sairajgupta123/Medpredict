"""Health-check endpoint."""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Check API health")
def health_check() -> dict[str, str]:
    """Return a lightweight status response without exposing secrets."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }
