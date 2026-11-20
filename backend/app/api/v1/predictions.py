"""Authenticated prediction history and privacy controls."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.models.prediction import Prediction
from app.schemas.prediction_history import (
    ConsentRevocationResponse,
    PredictionHistoryItem,
    PredictionHistoryPage,
)
from app.services.prediction_history import (
    delete_user_history_item,
    list_user_history,
    revoke_text_history_consent,
)

router = APIRouter(prefix="/predictions/history", tags=["Prediction history"])


@router.get("", response_model=PredictionHistoryPage)
def read_prediction_history(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PredictionHistoryPage:
    """List only the current user's history without returning health inputs."""
    items, total = list_user_history(
        db, user.id, limit=limit, offset=offset
    )
    return PredictionHistoryPage(
        items=[PredictionHistoryItem.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{prediction_id}/revoke-consent",
    response_model=ConsentRevocationResponse,
)
def revoke_prediction_history_consent(
    prediction_id: UUID,
    user: CurrentUser,
    db: DbSession,
) -> ConsentRevocationResponse:
    """Revoke text-history consent and erase retained free text and results."""
    prediction: Prediction = revoke_text_history_consent(
        db, user.id, prediction_id
    )
    return ConsentRevocationResponse(
        prediction_id=prediction.id,
        consent_revoked=True,
        retained_input_removed=prediction.input_text is None,
        message=(
            "History text and associated result details were removed. "
            "Future storage remains disabled for this prediction."
        ),
    )


@router.delete(
    "/{prediction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_prediction_history_item(
    prediction_id: UUID,
    user: CurrentUser,
    db: DbSession,
) -> None:
    """Delete one owned history item when no external image cleanup is needed."""
    delete_user_history_item(db, user.id, prediction_id)
