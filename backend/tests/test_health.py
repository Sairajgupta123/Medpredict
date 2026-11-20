"""Basic API smoke tests for liveness and database readiness."""

import pytest
from sqlalchemy.exc import SQLAlchemyError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app

client = TestClient(app)

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine)


@pytest.fixture()
def database_ready_client():
    """Override the database dependency with an isolated in-memory database."""
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_root_returns_service_information() -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "MediPredict API"
    assert body["status"] == "running"


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "MediPredict API"
    assert body["version"] == "0.1.0"


def test_readiness_endpoint_executes_database_query(database_ready_client: TestClient) -> None:
    response = database_ready_client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}


def test_openapi_document_is_available_in_development() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/health/ready" in schema["paths"]



def test_readiness_endpoint_returns_503_when_database_query_fails() -> None:
    """Report the service as not ready when PostgreSQL cannot execute a query."""
    class BrokenSession:
        def execute(self, statement):
            raise SQLAlchemyError("simulated database connection failure")

        def close(self) -> None:
            pass

    def override_get_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not ready."}
