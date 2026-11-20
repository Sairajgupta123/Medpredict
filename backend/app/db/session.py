"""Database engine and session lifecycle helpers."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# Engine creation is lazy with respect to network connections: PostgreSQL is
# contacted only when an actual database operation is performed.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield one request-scoped session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
