"""Validation helpers for already-deserialized research text-model bundles.

Only deserialize joblib artifacts from trusted storage: validation happens after
deserialization and cannot prevent code execution from a malicious pickle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


RESEARCH_PURPOSE = "research_only_not_for_clinical_use"


def validate_text_model_bundle(bundle: Any) -> dict[str, Any]:
    """Validate the structure and inference settings of a comparison-model bundle."""
    if not isinstance(bundle, Mapping):
        raise ValueError("Text model bundle must be a mapping")

    required = {
        "vectorizer",
        "estimator",
        "label_encoder",
        "model_name",
        "temperature",
        "minimum_confidence",
        "class_labels",
        "purpose",
    }
    missing = required - set(bundle)
    if missing:
        raise ValueError(f"Text model bundle is missing fields: {sorted(missing)}")

    vectorizer = bundle["vectorizer"]
    estimator = bundle["estimator"]
    label_encoder = bundle["label_encoder"]
    if not callable(getattr(vectorizer, "transform", None)):
        raise ValueError("Text model bundle vectorizer must expose transform()")
    if not callable(getattr(estimator, "predict_proba", None)):
        raise ValueError("Text model bundle estimator must expose predict_proba()")
    if not callable(getattr(estimator, "predict", None)):
        raise ValueError("Text model bundle estimator must expose predict()")

    class_labels = bundle["class_labels"]
    if (
        not isinstance(class_labels, (list, tuple))
        or len(class_labels) < 2
        or any(not isinstance(label, str) or not label.strip() for label in class_labels)
        or len(set(class_labels)) != len(class_labels)
    ):
        raise ValueError("class_labels must contain at least two unique non-empty strings")

    encoder_classes = getattr(label_encoder, "classes_", None)
    if encoder_classes is None or [str(label) for label in encoder_classes] != list(class_labels):
        raise ValueError("Text model bundle label encoder classes do not match class_labels")

    estimator_classes = getattr(estimator, "classes_", None)
    if estimator_classes is None:
        raise ValueError("Text model bundle estimator is missing fitted classes_")
    try:
        class_indices = np.asarray(estimator_classes)
    except (TypeError, ValueError) as exc:
        raise ValueError("Text model estimator classes_ must be integer class indices") from exc
    if (
        class_indices.ndim != 1
        or len(class_indices) != len(class_labels)
        or not np.issubdtype(class_indices.dtype, np.integer)
        or not np.array_equal(class_indices, np.arange(len(class_labels)))
    ):
        raise ValueError("Text model estimator classes_ do not match the encoded class order")

    model_name = bundle["model_name"]
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a non-empty string")
    if bundle["purpose"] != RESEARCH_PURPOSE:
        raise ValueError("Text model bundle must retain its research-only purpose marker")

    def finite_unit_interval(value: Any, name: str, *, positive: bool = False) -> float:
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, float, np.integer, np.floating))
            or not np.isfinite(value)
            or (value <= 0 if positive else not 0 <= value <= 1)
        ):
            expected = "a positive finite number" if positive else "a finite number in [0, 1]"
            raise ValueError(f"{name} must be {expected}")
        return float(value)

    temperature = finite_unit_interval(bundle["temperature"], "temperature", positive=True)
    minimum_confidence = finite_unit_interval(
        bundle["minimum_confidence"], "minimum_confidence"
    )
    return {
        "vectorizer": vectorizer,
        "estimator": estimator,
        "label_encoder": label_encoder,
        "model_name": model_name,
        "temperature": temperature,
        "minimum_confidence": minimum_confidence,
        "class_labels": list(class_labels),
        "purpose": RESEARCH_PURPOSE,
    }
