"""Evaluation helpers for skin-image experiments."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)


def classification_metrics(
    y_true: list[int] | np.ndarray,
    y_pred: list[int] | np.ndarray,
    *,
    class_names: list[str],
) -> dict[str, Any]:
    """Return class-aware metrics; class names and label order must be explicit."""
    if len(y_true) == 0 or len(y_pred) == 0:
        raise ValueError("Evaluation arrays cannot be empty")
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have equal lengths")
    if len(class_names) < 2 or len(set(class_names)) != len(class_names):
        raise ValueError("class_names must contain at least two unique labels")

    labels = list(range(len(class_names)))
    observed = set(np.asarray(y_true).tolist()) | set(np.asarray(y_pred).tolist())
    if not observed.issubset(set(labels)):
        raise ValueError("Observed class index is outside class_names mapping")

    return {
        "sample_count": int(len(y_true)),
        "macro_f1": float(
            f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
        ),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "confusion_matrix": confusion_matrix(
            y_true, y_pred, labels=labels
        ).tolist(),
        "per_class": classification_report(
            y_true,
            y_pred,
            labels=labels,
            target_names=class_names,
            output_dict=True,
            zero_division=0,
        ),
        "metrics_note": (
            "Metrics describe this evaluation partition only; they do not establish "
            "clinical validity or performance on other populations or image modalities."
        ),
    }
