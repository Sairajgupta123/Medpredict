"""Tests for the fail-closed skin-image inference contract."""

import math

import pytest

from app.services.skin_image_inference import (
    DisabledSkinImageModel,
    InvalidSkinImageModelOutput,
    SkinImageInferenceResult,
    SkinImageModelUnavailable,
)


MODEL_DIGEST = "a" * 64


def test_disabled_model_never_returns_a_fabricated_prediction() -> None:
    with pytest.raises(SkinImageModelUnavailable, match="no prediction was made"):
        DisabledSkinImageModel().predict(b"image", "image/jpeg")


def test_accepts_provenance_backed_calibrated_candidate() -> None:
    result = SkinImageInferenceResult(
        abstained=False,
        model_version="skin-model-1.0.0",
        model_artifact_sha256=MODEL_DIGEST,
        candidate_label="candidate_a",
        confidence=0.82,
        confidence_calibrated=True,
    )
    assert result.candidate_label == "candidate_a"
    assert result.confidence == 0.82


def test_accepts_explicit_abstention_without_candidate_or_confidence() -> None:
    result = SkinImageInferenceResult(
        abstained=True,
        model_version="skin-model-1.0.0",
        model_artifact_sha256=MODEL_DIGEST,
        abstention_reason="Image quality is insufficient.",
    )
    assert result.abstained is True
    assert result.candidate_label is None
    assert result.confidence is None


@pytest.mark.parametrize("confidence", [True, False, -0.01, 1.01, math.nan, math.inf, -math.inf])
def test_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(InvalidSkinImageModelOutput, match="finite value"):
        SkinImageInferenceResult(
            abstained=False,
            model_version="skin-model-1.0.0",
            model_artifact_sha256=MODEL_DIGEST,
            candidate_label="candidate_a",
            confidence=confidence,
            confidence_calibrated=True,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("abstained", 1, "abstained flag must be boolean"),
        ("confidence_calibrated", 1, "confidence_calibrated flag must be boolean"),
        ("candidate_label", 123, "valid candidate label"),
        ("abstention_reason", 123, "require a concise reason"),
    ],
)
def test_rejects_malformed_adapter_field_types(field, value, message) -> None:
    values = {
        "abstained": False,
        "model_version": "skin-model-1.0.0",
        "model_artifact_sha256": MODEL_DIGEST,
        "candidate_label": "candidate_a",
        "confidence": 0.8,
        "confidence_calibrated": True,
    }
    values[field] = value
    if field == "abstention_reason":
        values["abstained"] = True
        values.pop("candidate_label")
        values.pop("confidence")
        values.pop("confidence_calibrated")
    with pytest.raises(InvalidSkinImageModelOutput, match=message):
        SkinImageInferenceResult(**values)


def test_rejects_uncalibrated_confidence() -> None:
    with pytest.raises(InvalidSkinImageModelOutput, match="Uncalibrated"):
        SkinImageInferenceResult(
            abstained=False,
            model_version="skin-model-1.0.0",
            model_artifact_sha256=MODEL_DIGEST,
            candidate_label="candidate_a",
            confidence=0.8,
            confidence_calibrated=False,
        )


def test_rejects_missing_or_malformed_model_provenance() -> None:
    with pytest.raises(InvalidSkinImageModelOutput, match="model version"):
        SkinImageInferenceResult(
            abstained=True,
            model_version=" ",
            model_artifact_sha256=MODEL_DIGEST,
            abstention_reason="Model unavailable.",
        )
    with pytest.raises(InvalidSkinImageModelOutput, match="model version"):
        SkinImageInferenceResult(
            abstained=True,
            model_version=" skin-model-1.0.0 ",
            model_artifact_sha256=MODEL_DIGEST,
            abstention_reason="Model unavailable.",
        )
    with pytest.raises(InvalidSkinImageModelOutput, match="SHA-256"):
        SkinImageInferenceResult(
            abstained=True,
            model_version="skin-model-1.0.0",
            model_artifact_sha256="not-a-digest",
            abstention_reason="Model unavailable.",
        )


def test_abstention_cannot_leak_a_candidate_or_confidence() -> None:
    with pytest.raises(InvalidSkinImageModelOutput, match="must not contain"):
        SkinImageInferenceResult(
            abstained=True,
            model_version="skin-model-1.0.0",
            model_artifact_sha256=MODEL_DIGEST,
            candidate_label="candidate_a",
            confidence=0.7,
            abstention_reason="Insufficient quality.",
        )


def test_non_abstained_result_cannot_include_abstention_reason() -> None:
    with pytest.raises(InvalidSkinImageModelOutput, match="cannot include"):
        SkinImageInferenceResult(
            abstained=False,
            model_version="skin-model-1.0.0",
            model_artifact_sha256=MODEL_DIGEST,
            candidate_label="candidate_a",
            confidence=0.7,
            confidence_calibrated=True,
            abstention_reason="Uncertain.",
        )
