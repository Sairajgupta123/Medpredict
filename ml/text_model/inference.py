"""Validation helpers for already-deserialized research text-model bundles.

Only deserialize joblib artifacts from trusted storage: validation happens after
deserialization and cannot prevent code execution from a malicious pickle.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
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


def load_text_model_bundle(artifact_path: str | Path) -> dict[str, Any]:
    """Load a research bundle only after checking its adjacent integrity manifest.

    The path must point to an artifact in trusted, access-controlled storage. SHA-256
    verifies byte consistency with the manifest; it is not a signature. Never load
    user-supplied or otherwise untrusted joblib/pickle files: deserialization can execute
    code before structural validation runs.
    """
    path = Path(artifact_path)
    if not path.is_absolute():
        raise ValueError("Text model artifact path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Text model artifact must be an existing regular file")
    manifest_path = path.with_name("artifact_manifest.json")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Text model artifact manifest is missing or not a regular file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Text model artifact manifest is unreadable") from exc
    if not isinstance(manifest, Mapping):
        raise ValueError("Text model artifact manifest must be a JSON object")
    if manifest.get("purpose") != RESEARCH_PURPOSE:
        raise ValueError("Text model artifact manifest must be research-only")
    if manifest.get("artifact_file") != path.name:
        raise ValueError("Text model artifact filename does not match its manifest")
    expected_hash = manifest.get("artifact_sha256")
    if (
        not isinstance(expected_hash, str)
        or len(expected_hash) != 64
        or any(char not in "0123456789abcdef" for char in expected_hash)
    ):
        raise ValueError("Text model artifact manifest has an invalid SHA-256")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("Text model artifact SHA-256 does not match its manifest")

    # Only after the trusted-storage and integrity checks do we deserialize.
    try:
        bundle = joblib.load(path)
    except Exception as exc:
        raise ValueError("Text model artifact could not be deserialized") from exc
    validated = validate_text_model_bundle(bundle)
    if manifest.get("model_name") != validated["model_name"]:
        raise ValueError("Text model name does not match its artifact manifest")
    return validated


def predict_text_research(bundle: Any, text: str) -> dict[str, Any]:
    """Run one bounded research-only inference and abstain below the stored threshold.

    The artifact must come from trusted storage before this function is called. This helper
    deliberately does not expose a clinical prediction or disease-probability interpretation.
    """
    if not isinstance(text, str):
        raise TypeError("Symptom text must be a string")
    if not text.strip():
        raise ValueError("Symptom text must not be empty")
    if len(text) > 4_000:
        raise ValueError("Symptom text exceeds 4000 characters")

    validated = validate_text_model_bundle(bundle)
    features = validated["vectorizer"].transform([text.strip()])
    probabilities = np.asarray(
        validated["estimator"].predict_proba(features), dtype=np.float64
    )
    expected_shape = (1, len(validated["class_labels"]))
    if probabilities.shape != expected_shape:
        raise ValueError("Model probability output shape does not match class labels")
    if (
        not np.isfinite(probabilities).all()
        or (probabilities < 0).any()
        or (probabilities > 1).any()
    ):
        raise ValueError("Model probabilities must be finite values between zero and one")
    row_sums = probabilities.sum(axis=1)
    if not np.allclose(row_sums, 1.0, rtol=1e-5, atol=1e-7):
        raise ValueError("Model probability output must sum to one")

    # Temperature scaling is applied to log probabilities for numerical stability.
    log_scores = np.log(np.clip(probabilities[0], 1e-12, 1.0))
    scaled = log_scores / validated["temperature"]
    scaled -= np.max(scaled)
    calibrated = np.exp(scaled)
    calibrated /= calibrated.sum()
    best_index = int(np.argmax(calibrated))
    confidence = float(calibrated[best_index])
    accepted = confidence >= validated["minimum_confidence"]

    return {
        "status": "research_prediction" if accepted else "uncertain_abstained",
        "prediction": validated["class_labels"][best_index] if accepted else None,
        "confidence_score": confidence,
        "confidence_semantics": (
            "Maximum temperature-scaled model score; not a disease probability "
            "or medical certainty."
        ),
        "purpose": RESEARCH_PURPOSE,
        "clinical_interpretation_performed": False,
        "message": (
            "Research output for documented model classes only; not a diagnosis."
            if accepted
            else "The model abstained because its score was below the stored research threshold."
        ),
    }
