"""Temperature scaling and calibration metrics for offline skin-model research.

Temperature is fitted only on validation logits. Evaluate the fitted temperature once on an
untouched test partition. These metrics do not establish clinical validity.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp, softmax


def _validate_logits_and_targets(
    logits: list[list[float]] | np.ndarray,
    targets: list[int] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    scores = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(targets)
    if scores.ndim != 2 or scores.shape[0] == 0 or scores.shape[1] < 2:
        raise ValueError("logits must be a non-empty 2D array with at least two classes")
    if not np.isfinite(scores).all():
        raise ValueError("logits must contain only finite values")
    if labels.ndim != 1 or len(labels) != len(scores):
        raise ValueError("targets must be a 1D array matching the logits rows")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ValueError("targets must contain integer class indices")
    labels = labels.astype(np.int64, copy=False)
    if (labels < 0).any() or (labels >= scores.shape[1]).any():
        raise ValueError("target class index is outside logits columns")
    return scores, labels


def _validate_temperature(temperature: float) -> float:
    if (
        isinstance(temperature, (bool, np.bool_))
        or not isinstance(temperature, (int, float, np.integer, np.floating))
        or not np.isfinite(temperature)
        or temperature <= 0
    ):
        raise ValueError("temperature must be a positive finite number")
    return float(temperature)


def multiclass_nll(
    logits: list[list[float]] | np.ndarray,
    targets: list[int] | np.ndarray,
    *,
    temperature: float = 1.0,
) -> float:
    """Compute multiclass negative log likelihood after temperature scaling."""
    scores, labels = _validate_logits_and_targets(logits, targets)
    temperature = _validate_temperature(temperature)
    scaled = scores / temperature
    return float(np.mean(logsumexp(scaled, axis=1) - scaled[np.arange(len(labels)), labels]))


def fit_temperature(
    validation_logits: list[list[float]] | np.ndarray,
    validation_targets: list[int] | np.ndarray,
) -> float:
    """Fit a single positive temperature by minimizing validation negative log likelihood."""
    scores, labels = _validate_logits_and_targets(
        validation_logits, validation_targets
    )

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


def calibration_metrics(
    logits: list[list[float]] | np.ndarray,
    targets: list[int] | np.ndarray,
    *,
    temperature: float = 1.0,
    bins: int = 10,
) -> dict[str, Any]:
    """Calculate NLL, multiclass Brier score and top-label expected calibration error."""
    scores, labels = _validate_logits_and_targets(logits, targets)
    if isinstance(bins, bool) or not isinstance(bins, (int, np.integer)) or bins < 1:
        raise ValueError("bins must be a positive integer")
    temperature = _validate_temperature(temperature)

    probabilities = softmax(scores / temperature, axis=1)
    predictions = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = (predictions == labels).astype(np.float64)
    one_hot = np.eye(scores.shape[1], dtype=np.float64)[labels]
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))

    ece = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        if index == bins - 1:
            selected = (confidence >= edges[index]) & (confidence <= edges[index + 1])
        else:
            selected = (confidence >= edges[index]) & (confidence < edges[index + 1])
        if selected.any():
            ece += float(selected.mean()) * abs(
                float(correct[selected].mean())
                - float(confidence[selected].mean())
            )

    return {
        "sample_count": int(len(labels)),
        "temperature": float(temperature),
        "negative_log_likelihood": multiclass_nll(
            scores, labels, temperature=temperature
        ),
        "multiclass_brier_score": brier,
        "top_label_ece": float(ece),
        "ece_bins": int(bins),
        "note": (
            "Calibration metrics are partition- and dataset-specific. Fit temperature on "
            "validation logits only; report test metrics on an untouched test partition."
        ),
    }
