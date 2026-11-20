"""Tests for the public, read-only symptom vocabulary catalogue."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_catalog_returns_stable_ids_and_labels_without_aliases() -> None:
    response = client.get("/api/v1/symptoms/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["taxonomy_version"] == "0.1.0"
    assert body["clinical_interpretation_performed"] is False
    assert body["symptoms"]
    assert all({"id", "label", "category"} == set(item) for item in body["symptoms"])
    assert all("aliases" not in item for item in body["symptoms"])
    assert len({item["id"] for item in body["symptoms"]}) == len(body["symptoms"])


def test_catalog_discloses_unvalidated_research_status() -> None:
    response = client.get("/api/v1/symptoms/catalog")
    assert response.status_code == 200
    body = response.json()
    assert "not_clinically_validated" in body["status"]
    assert "not clinically validated" in body["disclaimer"]
