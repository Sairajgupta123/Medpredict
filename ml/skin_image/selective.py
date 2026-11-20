"""Confidence-based abstention helpers for research inference.

The confidence score is the maximum model probability. Unless a calibration step is explicitly
performed and validated, it must not be described as calibrated probability or medical certainty.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import accuracy_score, f1_score


def _validate_unit_interval(value: float, name: str, *, allow_zero: bool = True) -> float:
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, float, np.integer, np.floating))
        or not np.isfinite(value)
        or (value < 0 if allow_zero else value <= 0)
        or value > 1
    ):
        boundary = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must be a finite number in {boundary}")
    return float(value)


def apply_abstention(
    probabilities: list[list[float]] | np.ndarray,
    *,
    minimum_confidence: float,
) -> dict[str, Any]:
    """Return class indices for accepted rows and None for rows below the threshold."""
    values = np.asarray(probabilities, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] < 2:
        raise ValueError("probabilities must be a non-empty 2D array with at least two classes")
    if not np.isfinite(values).all():
        raise ValueError("probabilities must contain only finite values")
    if (values < 0).any() or (values > 1).any():
        raise ValueError("probabilities must be between 0 and 1")
    if not np.allclose(values.sum(axis=1), 1.0, atol=1e-5):
        raise ValueError("Each probability row must sum to 1")
    minimum_confidence = _validate_unit_interval(
        minimum_confidence, "minimum_confidence"
    )

    confidence = values.max(axis=1)
    predictions = values.argmax(axis=1)
    accepted = confidence >= minimum_confidence
    selective_predictions = [
        int(prediction) if keep else None
        for prediction, keep in zip(predictions, accepted)
    ]
    return {
        "predictions": selective_predictions,
        "confidence": confidence.tolist(),
        "accepted": accepted.tolist(),
        "accepted_count": int(accepted.sum()),
        "abstained_count": int((~accepted).sum()),
        "coverage": float(accepted.mean()),
        "minimum_confidence": float(minimum_confidence),
        "confidence_note": (
            "Maximum model score is not calibrated unless separately calibrated and validated; "
            "it is not a probability of disease or medical certainty."
        ),
    }


def selective_classification_metrics(
    y_true: list[int] | np.ndarray,
    probabilities: list[list[float]] | np.ndarray,
    *,
    minimum_confidence: float,
) -> dict[str, Any]:
    """Summarize coverage and performance on accepted examples only."""
    raw_targets = np.asarray(y_true)
    if not np.issubdtype(raw_targets.dtype, np.integer):
        raise ValueError("y_true values must be integer class indices")
    targets = raw_targets.astype(np.int64, copy=False)
    result = apply_abstention(
        probabilities,
        minimum_confidence=minimum_confidence,
    )
    if targets.ndim != 1 or len(targets) != len(result["predictions"]):
        raise ValueError("y_true must be a 1D array matching the probability rows")
    class_count = np.asarray(probabilities).shape[1]
    if (targets < 0).any() or (targets >= class_count).any():
        raise ValueError("y_true contains a class index outside the probability columns")

    accepted = np.asarray(result["accepted"], dtype=bool)
    predictions = np.asarray(
        [value for value in result["predictions"] if value is not None],
        dtype=np.int64,
    )
    accepted_targets = targets[accepted]
    if accepted.any():
        accepted_accuracy = float(accuracy_score(accepted_targets, predictions))
        accepted_macro_f1 = float(
            f1_score(
                accepted_targets,
                predictions,
                labels=list(range(np.asarray(probabilities).shape[1])),
                average="macro",
                zero_division=0,
            )
        )
    else:
        accepted_accuracy = None
        accepted_macro_f1 = None

    return {
        "sample_count": int(len(targets)),
        "coverage": result["coverage"],
        "accepted_count": result["accepted_count"],
        "abstained_count": result["abstained_count"],
        "accepted_accuracy": accepted_accuracy,
        "accepted_macro_f1": accepted_macro_f1,
        "minimum_confidence": result["minimum_confidence"],
        "note": (
            "Report coverage together with accepted-set metrics. Thresholds must be selected on "
            "validation data, then evaluated once on untouched test data."
        ),
    }


def select_threshold_for_coverage(
    validation_probabilities: list[list[float]] | np.ndarray,
    *,
    minimum_coverage: float,
) -> dict[str, float | int | str]:
    """Select an abstention cutoff using validation confidence scores only.

    This targets technical coverage, not clinical safety or a minimum accuracy guarantee.
    """
    values = np.asarray(validation_probabilities, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] < 2:
        raise ValueError(
            "validation_probabilities must be a non-empty 2D array with at least two classes"
        )
    if not np.isfinite(values).all():
        raise ValueError("validation_probabilities must contain only finite values")
    if (values < 0).any() or (values > 1).any():
        raise ValueError("validation_probabilities must be between 0 and 1")
    if not np.allclose(values.sum(axis=1), 1.0, atol=1e-5):
        raise ValueError("Each validation probability row must sum to 1")
    minimum_coverage = _validate_unit_interval(
        minimum_coverage, "minimum_coverage", allow_zero=False
    )

    confidence = values.max(axis=1)
    ordered = np.sort(confidence)[::-1]
    index = max(0, int(np.ceil(minimum_coverage * len(ordered))) - 1)
    threshold = float(ordered[index])
    achieved = float(np.mean(confidence >= threshold))
    return {
        "minimum_coverage_target": float(minimum_coverage),
        "threshold": threshold,
        "achieved_validation_coverage": achieved,
        "validation_sample_count": int(len(confidence)),
        "note": (
            "Threshold selected for technical validation coverage only. It is not a clinical "
            "safety threshold; report selective risk and coverage on an untouched test cohort."
        ),
    }
