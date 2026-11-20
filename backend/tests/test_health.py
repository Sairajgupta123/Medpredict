"""Basic API smoke tests."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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


def test_openapi_document_is_available_in_development() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/health" in schema["paths"]
