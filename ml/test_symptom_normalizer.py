"""Tests for conservative symptom phrase normalization."""

import json

import pytest

from ml.symptom_normalizer import load_taxonomy, normalize_phrase, normalize_symptoms


def test_maps_common_phrase_to_canonical_symptom() -> None:
    result = normalize_symptoms("My head hurts and I have a fever.")
    ids = {item["id"] for item in result["matched_symptoms"]}
    assert ids == {"SYM_HEADACHE", "SYM_FEVER"}
    assert result["clinical_interpretation_performed"] is False
    assert result["review_required"] is True


def test_case_and_punctuation_are_normalized() -> None:
    assert normalize_phrase("  FEVER!!!  ") == "fever"
    result = normalize_symptoms("THROAT hurts; also coughing.")
    ids = {item["id"] for item in result["matched_symptoms"]}
    assert "SYM_SORE_THROAT" in ids
    assert "SYM_COUGH" in ids


def test_phrase_matching_uses_token_boundaries() -> None:
    result = normalize_symptoms("I am not rashly worried.")
    assert result["matched_symptoms"] == []


def test_longer_phrase_is_preferred() -> None:
    result = normalize_symptoms("I have shortness of breath.")
    ids = [item["id"] for item in result["matched_symptoms"]]
    assert ids == ["SYM_SHORTNESS_OF_BREATH"]


def test_unknown_input_is_not_echoed() -> None:
    secret_like_text = "unlisted phrase user@example.com"
    result = normalize_symptoms(secret_like_text)
    assert result["matched_symptoms"] == []
    assert result["unrecognized_text_present"] is True
    assert secret_like_text not in json.dumps(result)


def test_empty_input_requires_review() -> None:
    result = normalize_symptoms("   ")
    assert result["reason"] == "empty_input"
    assert result["review_required"] is True


def test_non_string_input_is_rejected() -> None:
    with pytest.raises(TypeError):
        normalize_symptoms(None)  # type: ignore[arg-type]


def test_oversized_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        normalize_symptoms("a" * 4001)


def test_taxonomy_rejects_alias_collision(tmp_path) -> None:
    path = tmp_path / "bad_taxonomy.json"
    path.write_text(
        json.dumps(
            {
                "symptoms": [
                    {"id": "A", "label": "A", "category": "x", "aliases": ["fever"]},
                    {"id": "B", "label": "B", "category": "x", "aliases": ["FEVER!"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Alias collision"):
        load_taxonomy(path)
