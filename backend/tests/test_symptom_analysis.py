"""Tests for the non-diagnostic symptom phrase endpoint and structured context."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
DEFAULT_CONTEXT = {
    "duration": "not_sure",
    "severity": "not_sure",
    "onset": "not_sure",
}


def request_payload(text: str, **context: str) -> dict:
    return {"text": text, "reported_context": {**DEFAULT_CONTEXT, **context}}


def test_normalize_recognizes_supported_phrases_without_diagnosis() -> None:
    response = client.post(
        "/api/v1/symptoms/normalize",
        json=request_payload("I have a headache and fever."),
    )
    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body["matched_symptoms"]} == {
        "SYM_HEADACHE",
        "SYM_FEVER",
    }
    assert body["clinical_interpretation_performed"] is False
    assert body["model_inference_performed"] is False
    assert body["disease_prediction_performed"] is False
    assert body["research_only"] is True
    assert body["review_required"] is True
    assert "does not diagnose" in body["disclaimer"]
    assert body["reported_context"] == DEFAULT_CONTEXT


def test_normalize_flags_negated_mentions_separately() -> None:
    response = client.post(
        "/api/v1/symptoms/normalize",
        json=request_payload("I have no fever but I have a cough."),
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
        json=request_payload(private_text),
    )
    assert response.status_code == 200
    assert private_text not in response.text
    assert response.json()["unrecognized_text_present"] is True


def test_normalize_rejects_empty_or_oversized_input() -> None:
    empty = client.post(
        "/api/v1/symptoms/normalize",
        json=request_payload("   "),
    )
    oversized = client.post(
        "/api/v1/symptoms/normalize",
        json=request_payload("x" * 4001),
    )
    assert empty.status_code == 422
    assert oversized.status_code == 422


def test_normalize_returns_self_reported_context_without_interpreting_it() -> None:
    context = {
        "duration": "four_to_seven_days",
        "severity": "moderate",
        "onset": "comes_and_goes",
    }
    response = client.post(
        "/api/v1/symptoms/normalize",
        json=request_payload("I have a cough.", **context),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reported_context"] == context
    assert body["clinical_interpretation_performed"] is False


def test_normalize_rejects_unknown_context_values_and_extra_fields() -> None:
    invalid_value = client.post(
        "/api/v1/symptoms/normalize",
        json=request_payload("I have a cough.", severity="extreme"),
    )
    extra_field = client.post(
        "/api/v1/symptoms/normalize",
        json={
            **request_payload("I have a cough."),
            "unexpected": "must be rejected",
        },
    )
    assert invalid_value.status_code == 422
    assert extra_field.status_code == 422


def test_normalize_requires_reported_context() -> None:
    response = client.post(
        "/api/v1/symptoms/normalize",
        json={"text": "I have a cough."},
    )
    assert response.status_code == 422
