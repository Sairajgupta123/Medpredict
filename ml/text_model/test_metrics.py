"""Tests for explicit class-aware symptom-text metrics."""

import pytest

from ml.text_model.metrics import evaluate_predictions


def test_metrics_include_every_class_and_per_class_rates() -> None:
    result = evaluate_predictions(
        [0, 0, 1, 1, 2],
        [0, 1, 1, 1, 2],
        class_labels=["A", "B", "C"],
    )
    assert result["sample_count"] == 5
    assert result["macro_f1"] >= 0
    assert len(result["confusion_matrix"]) == 3
    assert result["per_class_sensitivity_specificity"]["A"]["sensitivity"] == 0.5
    assert result["per_class_sensitivity_specificity"]["A"]["specificity"] == 1.0


def test_metrics_keep_zero_support_class_visible() -> None:
    result = evaluate_predictions(
        [0, 0, 1],
        [0, 1, 1],
        class_labels=["A", "B", "C"],
    )
    assert result["per_class_sensitivity_specificity"]["C"]["support"] == 0
    assert result["classification_report"]["C"]["support"] == 0


def test_metrics_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_predictions([], [], class_labels=["A", "B"])
    with pytest.raises(ValueError, match="equal lengths"):
        evaluate_predictions([0, 1], [0], class_labels=["A", "B"])
    with pytest.raises(ValueError, match="outside"):
        evaluate_predictions([0, 2], [0, 1], class_labels=["A", "B"])
    with pytest.raises(ValueError, match="unique"):
        evaluate_predictions([0, 1], [0, 1], class_labels=["A", "A"])

def test_balanced_accuracy_includes_configured_class_with_zero_support() -> None:
    result = evaluate_predictions(
        [0, 0, 1, 1],
        [0, 0, 1, 1],
        class_labels=["A", "B", "C"],
    )
    assert result["balanced_accuracy"] == pytest.approx(2 / 3)
    assert result["per_class_sensitivity_specificity"]["C"]["support"] == 0


def test_metrics_reject_blank_class_labels() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_predictions([0, 1], [0, 1], class_labels=["A", " "])
