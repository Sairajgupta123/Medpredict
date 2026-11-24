"""Database engine and session lifecycle helpers."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# Engine creation is lazy with respect to network connections: PostgreSQL is
# contacted only when an actual database operation is performed.
engine_options: dict[str, object] = {
    "pool_pre_ping": True,
    "pool_size": settings.database_pool_size,
    "max_overflow": settings.database_max_overflow,
    "pool_timeout": settings.database_pool_timeout_seconds,
    "pool_recycle": settings.database_pool_recycle_seconds,
}

# Bound connection establishment time for PostgreSQL API and worker processes.
if settings.database_url.lower().startswith(("postgresql://", "postgresql+")):
    engine_options["connect_args"] = {
        "connect_timeout": settings.database_connect_timeout_seconds,
    }

engine = create_engine(settings.database_url, **engine_options)

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
