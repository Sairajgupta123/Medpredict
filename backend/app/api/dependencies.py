"""Shared API dependencies for authenticated routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: DbSession,
) -> User:
    """Resolve the active user from a valid bearer access token."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    token_identity = decode_access_token(credentials.credentials)
    if token_identity is None:
        raise unauthorized

    user_id, token_version = token_identity
    user = db.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or user.token_version != token_version
    ):
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_catalog_reviewer(user: CurrentUser) -> User:
    """Allow only explicitly provisioned reviewers and admins to review catalog data."""
    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Catalog reviewer permission required.",
        )
    return user


CatalogReviewer = Annotated[User, Depends(require_catalog_reviewer)]


def require_admin(user: CurrentUser) -> User:
    """Restrict operational governance data to administrators only."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator permission required.",
        )
    return user


Administrator = Annotated[User, Depends(require_admin)]
