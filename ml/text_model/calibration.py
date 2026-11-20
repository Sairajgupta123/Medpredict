"""Validation-fitted calibration for symptom-text model probabilities."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp, softmax


def _positive_finite_number(value: Any, name: str) -> float:
    """Accept real numeric scalars only; reject booleans, strings and non-finite values."""
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, float, np.integer, np.floating))
        or not np.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be positive and finite")
    return float(value)


def _unit_interval_number(value: Any, name: str) -> float:
    """Validate a finite numeric threshold in the closed unit interval."""
    if (
        isinstance(value, (bool, np.bool_))
        or not isinstance(value, (int, float, np.integer, np.floating))
        or not np.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return float(value)


def _validate(
    probabilities: list[list[float]] | np.ndarray,
    targets: list[int] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(probabilities, dtype=np.float64)
    labels = np.asarray(targets)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] < 2:
        raise ValueError("probabilities must be a non-empty 2D array with at least two classes")
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("probabilities must be finite and non-negative")
    row_sums = values.sum(axis=1)
    if not np.isfinite(row_sums).all() or (row_sums <= 0).any():
        raise ValueError("each probability row must have a positive finite sum")
    values = values / row_sums[:, None]
    if labels.ndim != 1 or len(labels) != len(values):
        raise ValueError("targets must be a 1D array matching probability rows")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("targets must contain integer class indices")
    labels = labels.astype(np.int64, copy=False)
    if (labels < 0).any() or (labels >= values.shape[1]).any():
        raise ValueError("target class index is outside probability columns")
    return values, labels


def _logits(probabilities: np.ndarray) -> np.ndarray:
    return np.log(np.clip(probabilities, 1e-12, 1.0))


def fit_temperature(
    validation_probabilities: list[list[float]] | np.ndarray,
    validation_targets: list[int] | np.ndarray,
) -> float:
    """Fit positive scalar temperature using validation probabilities only."""
    values, labels = _validate(validation_probabilities, validation_targets)
    scores = _logits(values)

    def objective(log_temperature: float) -> float:
        temperature = float(np.exp(log_temperature))
        scaled = scores / temperature
        return float(
            np.mean(
                logsumexp(scaled, axis=1)
                - scaled[np.arange(len(labels)), labels]
            )
        )

    result = minimize_scalar(
        objective,
        bounds=(-3.0, 3.0),
        method="bounded",
        options={"xatol": 1e-5},
    )
    if not result.success or not np.isfinite(result.fun):
        raise RuntimeError("Temperature calibration optimization did not converge")
    return float(np.exp(result.x))


def apply_temperature(
    probabilities: list[list[float]] | np.ndarray,
    *,
    temperature: float,
) -> np.ndarray:
    """Return normalized, temperature-scaled probabilities."""
    values = np.asarray(probabilities, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] < 2:
        raise ValueError("probabilities must be a non-empty 2D array with at least two classes")
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("probabilities must be finite and non-negative")
    row_sums = values.sum(axis=1)
    if (row_sums <= 0).any():
        raise ValueError("each probability row must have a positive sum")
    temperature = _positive_finite_number(temperature, "temperature")
    normalized = values / row_sums[:, None]
    return softmax(_logits(normalized) / temperature, axis=1)


def calibration_metrics(
    probabilities: list[list[float]] | np.ndarray,
    targets: list[int] | np.ndarray,
    *,
    temperature: float = 1.0,
    bins: int = 10,
) -> dict[str, Any]:
    """Report NLL, multiclass Brier score and top-label expected calibration error."""
    values, labels = _validate(probabilities, targets)
    if isinstance(bins, (bool, np.bool_)) or not isinstance(bins, (int, np.integer)) or bins < 1:
        raise ValueError("bins must be a positive integer")
    calibrated = apply_temperature(values, temperature=temperature)
    predicted = calibrated.argmax(axis=1)
    confidence = calibrated.max(axis=1)
    correct = (predicted == labels).astype(np.float64)
    one_hot = np.eye(calibrated.shape[1], dtype=np.float64)[labels]
    nll = float(
        np.mean(
            -np.log(
                np.clip(calibrated[np.arange(len(labels)), labels], 1e-12, 1.0)
            )
        )
    )
    brier = float(np.mean(np.sum((calibrated - one_hot) ** 2, axis=1)))
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for index in range(bins):
        mask = (
            (confidence >= edges[index])
            & (
                (confidence <= edges[index + 1])
                if index == bins - 1
                else (confidence < edges[index + 1])
            )
        )
        if mask.any():
            ece += float(mask.mean()) * abs(
                float(correct[mask].mean()) - float(confidence[mask].mean())
            )
    return {
        "sample_count": int(len(labels)),
        "temperature": float(temperature),
        "negative_log_likelihood": nll,
        "multiclass_brier_score": brier,
        "top_label_ece": float(ece),
        "ece_bins": int(bins),
        "note": "Fit temperature on validation data only; test metrics must use an untouched cohort.",
    }


def selective_predictions(
    probabilities: list[list[float]] | np.ndarray,
    *,
    minimum_confidence: float,
    temperature: float = 1.0,
) -> dict[str, Any]:
    """Return class indices only above a validation-selected confidence threshold."""
    calibrated = apply_temperature(probabilities, temperature=temperature)
    minimum_confidence = _unit_interval_number(
        minimum_confidence, "minimum_confidence"
    )
    confidence = calibrated.max(axis=1)
    raw_predictions = calibrated.argmax(axis=1)
    predictions = [
        int(label) if score >= minimum_confidence else None
        for label, score in zip(raw_predictions, confidence, strict=True)
    ]
    return {
        "predictions": predictions,
        "confidence_scores": confidence.astype(float).tolist(),
        "accepted_count": int(sum(label is not None for label in predictions)),
        "sample_count": int(len(predictions)),
        "coverage": float(np.mean([label is not None for label in predictions])),
        "confidence_semantics": (
            "Maximum temperature-scaled model score, not a disease probability or medical certainty."
        ),
    }


def select_threshold_for_coverage(
    validation_probabilities: list[list[float]] | np.ndarray,
    *,
    minimum_coverage: float,
    temperature: float = 1.0,
) -> dict[str, float]:
    """Choose a confidence cutoff on validation data for a requested coverage target.

    The threshold is a technical operating point, not a clinically safe threshold.
    """
    minimum_coverage = _unit_interval_number(
        minimum_coverage, "minimum_coverage"
    )
    if minimum_coverage == 0:
        raise ValueError("minimum_coverage must be in (0, 1]")
    calibrated = apply_temperature(
        validation_probabilities, temperature=temperature
    )
    confidence = np.sort(calibrated.max(axis=1))[::-1]
    index = max(0, int(np.ceil(minimum_coverage * len(confidence))) - 1)
    threshold = float(confidence[index])
    achieved = float(np.mean(confidence >= threshold))
    return {
        "minimum_coverage_target": float(minimum_coverage),
        "threshold": threshold,
        "achieved_validation_coverage": achieved,
        "validation_sample_count": int(len(confidence)),
        "note": (
            "Threshold selected for technical coverage only; validate selective risk "
            "and clinical safety on an independent cohort."
        ),
    }
