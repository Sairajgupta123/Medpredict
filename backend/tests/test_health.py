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



def test_research_model_status_reports_models_not_configured(monkeypatch) -> None:
    from app.api.v1 import health
    from app.core.config import Settings

    monkeypatch.setattr(health, "get_settings", lambda: Settings())
    response = client.get("/api/v1/models/status")

    assert response.status_code == 200
    body = response.json()
    assert body["skin_image"] == {
        "status": "not_configured",
        "configured": False,
        "loaded": False,
        "inference_enabled": False,
    }
    assert body["symptom_text"]["status"] == "not_configured"
    assert body["research_only"] is True
    assert body["clinical_diagnosis_enabled"] is False


def test_research_model_status_never_claims_configured_path_is_loaded(monkeypatch) -> None:
    from app.api.v1 import health
    from app.core.config import Settings

    settings = Settings(
        skin_research_checkpoint_path="/srv/private/skin/model.pt",
        text_research_artifact_path="relative/model.joblib",
    )
    monkeypatch.setattr(health, "get_settings", lambda: settings)
    response = client.get("/api/v1/models/status")

    assert response.status_code == 200
    body = response.json()
    assert body["skin_image"]["status"] == "configured_not_loaded"
    assert body["skin_image"]["loaded"] is False
    assert body["skin_image"]["inference_enabled"] is False
    assert body["symptom_text"]["status"] == "invalid_configuration"


def test_research_model_status_never_exposes_configured_paths(monkeypatch) -> None:
    from app.api.v1 import health
    from app.core.config import Settings

    private_skin_path = "/srv/private/medipredict/skin-checkpoint.pt"
    private_text_path = "/srv/private/medipredict/text-model.joblib"
    settings = Settings(
        skin_research_checkpoint_path=private_skin_path,
        text_research_artifact_path=private_text_path,
    )
    monkeypatch.setattr(health, "get_settings", lambda: settings)

    response = client.get("/api/v1/models/status")

    assert response.status_code == 200
    assert private_skin_path not in response.text
    assert private_text_path not in response.text
    body = response.json()
    for capability in (body["skin_image"], body["symptom_text"]):
        assert capability["configured"] is True
        assert capability["loaded"] is False
        assert capability["inference_enabled"] is False

