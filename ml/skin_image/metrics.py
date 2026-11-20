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
    actual = np.asarray(y_true)
    predicted = np.asarray(y_pred)
    if not np.issubdtype(actual.dtype, np.integer) or not np.issubdtype(
        predicted.dtype, np.integer
    ):
        raise ValueError("Class indices must be integers")
    observed = set(actual.tolist()) | set(predicted.tolist())
    if not observed.issubset(set(labels)):
        raise ValueError("Observed class index is outside class_names mapping")

    matrix = confusion_matrix(actual, predicted, labels=labels)
    per_class_report = classification_report(
        actual,
        predicted,
        labels=labels,
        target_names=class_names,
        output_dict=True,
        zero_division=0,
    )
    per_class_rates: dict[str, dict[str, float | int]] = {}
    for index, name in enumerate(class_names):
        true_positive = int(matrix[index, index])
        false_negative = int(matrix[index, :].sum() - true_positive)
        false_positive = int(matrix[:, index].sum() - true_positive)
        true_negative = int(matrix.sum() - true_positive - false_negative - false_positive)
        sensitivity_denominator = true_positive + false_negative
        specificity_denominator = true_negative + false_positive
        per_class_rates[name] = {
            "sensitivity": (
                true_positive / sensitivity_denominator
                if sensitivity_denominator
                else 0.0
            ),
            "specificity": (
                true_negative / specificity_denominator
                if specificity_denominator
                else 0.0
            ),
            "support": sensitivity_denominator,
        }

    return {
        "sample_count": int(len(actual)),
        "macro_f1": float(
            f1_score(actual, predicted, labels=labels, average="macro", zero_division=0)
        ),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "confusion_matrix": matrix.tolist(),
        "per_class": per_class_report,
        "per_class_sensitivity_specificity": per_class_rates,
        "metrics_note": (
            "Metrics describe this evaluation partition only; they do not establish "
            "clinical validity or performance on other populations or image modalities. "
            "A zero rate may reflect absent support and must be interpreted with counts."
        ),
    }
