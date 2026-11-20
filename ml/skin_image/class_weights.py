"""Training-partition class weights for imbalanced classification experiments."""

from __future__ import annotations

from typing import Any

import numpy as np


def calculate_class_weights(
    labels: list[int] | np.ndarray,
    *,
    class_count: int,
) -> dict[str, Any]:
    """Calculate balanced weights from training labels only.

    Classes absent from the training partition are rejected rather than assigned arbitrary
    weights. Callers must never pass validation or test labels to this function.
    """
    values = np.asarray(labels)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("labels must be a non-empty 1D array")
    if not np.issubdtype(values.dtype, np.integer):
        raise ValueError("labels must contain integer class indices")
    if class_count < 2:
        raise ValueError("class_count must be at least 2")
    values = values.astype(np.int64, copy=False)
    if (values < 0).any() or (values >= class_count).any():
        raise ValueError("label index is outside the configured class range")

    counts = np.bincount(values, minlength=class_count)
    if (counts == 0).any():
        missing = np.flatnonzero(counts == 0).tolist()
        raise ValueError(f"Training partition is missing class indices: {missing}")

    total = int(counts.sum())
    weights = total / (class_count * counts.astype(np.float64))
    return {
        "class_counts": counts.astype(int).tolist(),
        "class_weights": weights.astype(float).tolist(),
        "method": "balanced_inverse_frequency",
        "source_partition": "training_only",
        "note": (
            "Weights must be computed from training labels only. They do not correct "
            "sampling bias or guarantee improved minority-class clinical performance."
        ),
    }
