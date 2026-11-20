"""Tests for the skin model factory and classification metrics."""

import pytest

from ml.skin_image.metrics import classification_metrics


def test_metrics_include_macro_f1_and_per_class_results() -> None:
    result = classification_metrics(
        [0, 0, 1, 1, 2],
        [0, 1, 1, 1, 2],
        class_names=["class_a", "class_b", "class_c"],
    )
    assert result["sample_count"] == 5
    assert 0 <= result["macro_f1"] <= 1
    assert len(result["confusion_matrix"]) == 3
    assert "class_a" in result["per_class"]


def test_metrics_reject_empty_or_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        classification_metrics([], [], class_names=["a", "b"])
    with pytest.raises(ValueError, match="equal lengths"):
        classification_metrics([0, 1], [0], class_names=["a", "b"])


def test_metrics_reject_unknown_class_index() -> None:
    with pytest.raises(ValueError, match="outside"):
        classification_metrics([0, 2], [0, 1], class_names=["a", "b"])


def test_metrics_reject_duplicate_class_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        classification_metrics([0, 1], [0, 1], class_names=["same", "same"])
