"""Class-aware evaluation helpers for symptom-text experiments."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)


def evaluate_predictions(
    y_true: list[int] | np.ndarray,
    y_pred: list[int] | np.ndarray,
    *,
    class_labels: list[str],
) -> dict[str, Any]:
    """Report metrics for the complete, explicit class order."""
    actual = np.asarray(y_true)
    predicted = np.asarray(y_pred)
    if actual.ndim != 1 or predicted.ndim != 1 or actual.size == 0:
        raise ValueError("Evaluation labels must be non-empty 1D arrays")
    if len(actual) != len(predicted):
        raise ValueError("y_true and y_pred must have equal lengths")
    if len(class_labels) < 2 or len(set(class_labels)) != len(class_labels):
        raise ValueError("class_labels must contain at least two unique labels")
    expected = set(range(len(class_labels)))
    if not np.issubdtype(actual.dtype, np.integer) or not np.issubdtype(
        predicted.dtype, np.integer
    ):
        raise ValueError("Encoded class indices must be integers")
    observed = set(actual.tolist()) | set(predicted.tolist())
    if not observed.issubset(expected):
        raise ValueError("Observed class index is outside class_labels mapping")

    matrix = confusion_matrix(actual, predicted, labels=list(range(len(class_labels))))
    report = classification_report(
        actual,
        predicted,
        labels=list(range(len(class_labels))),
        target_names=class_labels,
        output_dict=True,
        zero_division=0,
    )
    per_class: dict[str, dict[str, float | int]] = {}
    for index, name in enumerate(class_labels):
        tp = int(matrix[index, index])
        fn = int(matrix[index, :].sum() - tp)
        fp = int(matrix[:, index].sum() - tp)
        tn = int(matrix.sum() - tp - fn - fp)
        per_class[name] = {
            "sensitivity": tp / (tp + fn) if tp + fn else 0.0,
            "specificity": tn / (tn + fp) if tn + fp else 0.0,
            "support": tp + fn,
        }

    return {
        "sample_count": int(actual.size),
        "class_labels": class_labels,
        "macro_f1": float(
            f1_score(
                actual,
                predicted,
                labels=list(range(len(class_labels))),
                average="macro",
                zero_division=0,
            )
        ),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "confusion_matrix": matrix.tolist(),
        "classification_report": report,
        "per_class_sensitivity_specificity": per_class,
        "note": (
            "Partition-specific research metrics only. Interpret each rate with support; "
            "these metrics do not establish clinical validity."
        ),
    }
