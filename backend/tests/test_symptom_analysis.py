"""Tests for the non-diagnostic symptom phrase endpoint."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_normalize_recognizes_supported_phrases_without_diagnosis() -> None:
    response = client.post(
        "/api/v1/symptoms/normalize",
        json={"text": "I have a headache and fever."},
    )
    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body["matched_symptoms"]} == {
        "SYM_HEADACHE",
        "SYM_FEVER",
    }
    assert body["clinical_interpretation_performed"] is False
    assert body["review_required"] is True
    assert "does not diagnose" in body["disclaimer"]


def test_normalize_flags_negated_mentions_separately() -> None:
    response = client.post(
        "/api/v1/symptoms/normalize",
        json={"text": "I have no fever but I have a cough."},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["matched_symptoms"]] == ["SYM_COUGH"]
    assert body["contextual_mentions"][0]["id"] == "SYM_FEVER"
    assert body["contextual_mentions"][0]["context_flag"] == "negated_or_denied_context"


def test_normalize_does_not_echo_unrecognized_text() -> None:
    private_text = "private phrase user@example.com"
    response = client.post(
        "/api/v1/symptoms/normalize",
        json={"text": private_text},
    )
    assert response.status_code == 200
    assert private_text not in response.text
    assert response.json()["unrecognized_text_present"] is True


def test_normalize_rejects_empty_or_oversized_input() -> None:
    empty = client.post("/api/v1/symptoms/normalize", json={"text": "   "})
    oversized = client.post(
        "/api/v1/symptoms/normalize",
        json={"text": "x" * 4001},
    )
    assert empty.status_code == 422
    assert oversized.status_code == 422
