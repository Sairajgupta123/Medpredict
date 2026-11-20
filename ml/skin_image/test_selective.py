"""Tests for confidence-based selective prediction and abstention."""

import pytest

from ml.skin_image.selective import apply_abstention, selective_classification_metrics


def test_abstention_marks_low_confidence_predictions_as_none() -> None:
    result = apply_abstention(
        [[0.90, 0.10], [0.51, 0.49], [0.20, 0.80]],
        minimum_confidence=0.75,
    )
    assert result["predictions"] == [0, None, 1]
    assert result["accepted_count"] == 2
    assert result["abstained_count"] == 1
    assert result["coverage"] == pytest.approx(2 / 3)


def test_abstention_rejects_invalid_probability_rows() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        apply_abstention([[0.2, 0.2]], minimum_confidence=0.5)
    with pytest.raises(ValueError, match="finite"):
        apply_abstention([[float("nan"), 0.0]], minimum_confidence=0.5)


def test_abstention_threshold_boundaries() -> None:
    result = apply_abstention([[0.5, 0.5]], minimum_confidence=0.5)
    assert result["accepted"] == [True]
    result = apply_abstention([[0.5, 0.5]], minimum_confidence=0.51)
    assert result["accepted"] == [False]


def test_selective_metrics_report_coverage_and_accepted_metrics() -> None:
    result = selective_classification_metrics(
        [0, 1, 1],
        [[0.9, 0.1], [0.6, 0.4], [0.1, 0.9]],
        minimum_confidence=0.7,
    )
    assert result["coverage"] == pytest.approx(2 / 3)
    assert result["accepted_count"] == 2
    assert result["accepted_accuracy"] == 1.0


def test_selective_metrics_handle_zero_coverage() -> None:
    result = selective_classification_metrics(
        [0],
        [[0.51, 0.49]],
        minimum_confidence=0.9,
    )
    assert result["coverage"] == 0.0
    assert result["accepted_accuracy"] is None
