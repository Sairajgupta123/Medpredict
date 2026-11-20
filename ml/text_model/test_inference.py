"""Tests for research text-model bundle validation."""

import numpy as np
import pytest


class FakeVectorizer:
    def transform(self, values):
        return values


class FakeEstimator:
    classes_ = np.asarray([0, 1])

    def predict(self, values):
        return np.zeros(len(values), dtype=int)

    def predict_proba(self, values):
        return np.tile([0.5, 0.5], (len(values), 1))


class FakeLabelEncoder:
    classes_ = np.asarray(["class_a", "class_b"])


def valid_bundle():
    return {
        "vectorizer": FakeVectorizer(),
        "estimator": FakeEstimator(),
        "label_encoder": FakeLabelEncoder(),
        "model_name": "logistic_regression",
        "temperature": 1.25,
        "minimum_confidence": 0.7,
        "class_labels": ["class_a", "class_b"],
        "purpose": "research_only_not_for_clinical_use",
    }


def test_valid_bundle_returns_normalized_inference_settings() -> None:
    from ml.text_model.inference import validate_text_model_bundle

    result = validate_text_model_bundle(valid_bundle())
    assert result["class_labels"] == ["class_a", "class_b"]
    assert result["temperature"] == 1.25
    assert result["minimum_confidence"] == 0.7
    assert result["purpose"] == "research_only_not_for_clinical_use"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("class_labels", ["class_a", "class_a"], "unique non-empty"),
        ("class_labels", ["class_a", " "], "unique non-empty"),
        ("model_name", "", "model_name"),
        ("purpose", "clinical", "research-only"),
        ("temperature", True, "temperature"),
        ("temperature", float("nan"), "temperature"),
        ("temperature", 0, "temperature"),
        ("minimum_confidence", True, "minimum_confidence"),
        ("minimum_confidence", float("inf"), "minimum_confidence"),
        ("minimum_confidence", 1.1, "minimum_confidence"),
    ],
)
def test_bundle_rejects_invalid_metadata(field, value, message) -> None:
    from ml.text_model.inference import validate_text_model_bundle

    bundle = valid_bundle()
    bundle[field] = value
    with pytest.raises(ValueError, match=message):
        validate_text_model_bundle(bundle)


def test_bundle_rejects_mismatched_label_encoder_order() -> None:
    from ml.text_model.inference import validate_text_model_bundle

    bundle = valid_bundle()
    bundle["label_encoder"].classes_ = np.asarray(["class_b", "class_a"])
    with pytest.raises(ValueError, match="label encoder"):
        validate_text_model_bundle(bundle)


def test_bundle_rejects_mismatched_estimator_class_indices() -> None:
    from ml.text_model.inference import validate_text_model_bundle

    bundle = valid_bundle()
    bundle["estimator"].classes_ = np.asarray([1, 2])
    with pytest.raises(ValueError, match="encoded class order"):
        validate_text_model_bundle(bundle)


def test_bundle_rejects_missing_inference_methods() -> None:
    from ml.text_model.inference import validate_text_model_bundle

    bundle = valid_bundle()
    bundle["vectorizer"] = object()
    with pytest.raises(ValueError, match="transform"):
        validate_text_model_bundle(bundle)
