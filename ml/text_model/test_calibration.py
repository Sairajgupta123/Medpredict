"""Tests for text probability calibration and selective prediction."""

import numpy as np
import pytest

from ml.text_model.calibration import (
    apply_temperature,
    calibration_metrics,
    fit_temperature,
    selective_predictions,
    select_threshold_for_coverage,
)


def test_temperature_is_positive_and_deterministic() -> None:
    probabilities = [[0.95, 0.05], [0.05, 0.95], [0.8, 0.2], [0.2, 0.8]]
    targets = [0, 1, 1, 0]
    first = fit_temperature(probabilities, targets)
    second = fit_temperature(probabilities, targets)
    assert first > 0
    assert first == pytest.approx(second)


def test_calibration_metrics_are_bounded() -> None:
    result = calibration_metrics(
        [[0.8, 0.2], [0.1, 0.9]],
        [0, 1],
        temperature=1.2,
        bins=5,
    )
    assert result["sample_count"] == 2
    assert 0 <= result["top_label_ece"] <= 1
    assert 0 <= result["multiclass_brier_score"] <= 2


def test_temperature_preserves_probability_rows() -> None:
    result = apply_temperature([[0.7, 0.3], [0.4, 0.6]], temperature=1.5)
    assert np.allclose(result.sum(axis=1), 1.0)
    assert (result >= 0).all()


def test_selective_prediction_abstains_below_threshold() -> None:
    result = selective_predictions(
        [[0.55, 0.45], [0.95, 0.05]],
        minimum_confidence=0.8,
    )
    assert result["predictions"][0] is None
    assert result["predictions"][1] == 0
    assert result["accepted_count"] == 1
    assert result["coverage"] == 0.5


def test_calibration_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        fit_temperature([[1.1, -0.1]], [0])
    with pytest.raises(ValueError, match="integer class indices"):
        fit_temperature([[0.8, 0.2]], [0.5])
    with pytest.raises(ValueError, match="outside"):
        calibration_metrics([[0.8, 0.2]], [2])
    with pytest.raises(ValueError, match="positive and finite"):
        apply_temperature([[0.8, 0.2]], temperature=0)


def test_threshold_is_selected_from_validation_probabilities() -> None:
    result = select_threshold_for_coverage(
        [[0.9, 0.1], [0.8, 0.2], [0.55, 0.45], [0.51, 0.49]],
        minimum_coverage=0.5,
    )
    assert result["threshold"] > 0.5
    assert result["achieved_validation_coverage"] >= 0.5
    assert result["validation_sample_count"] == 4


def test_threshold_rejects_invalid_coverage_target() -> None:
    with pytest.raises(ValueError, match="minimum_coverage"):
        select_threshold_for_coverage(
            [[0.8, 0.2]], minimum_coverage=0
        )

@pytest.mark.parametrize("temperature", [True, False, "1.0", float("nan"), float("inf")])
def test_apply_temperature_rejects_invalid_temperature_types(temperature) -> None:
    with pytest.raises(ValueError, match="temperature"):
        apply_temperature([[0.8, 0.2]], temperature=temperature)


@pytest.mark.parametrize("bins", [True, False, 2.5, "5"])
def test_calibration_metrics_rejects_non_integer_bins(bins) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        calibration_metrics([[0.8, 0.2]], [0], bins=bins)


@pytest.mark.parametrize("threshold", [True, False, "0.5", float("nan"), float("inf")])
def test_selective_predictions_rejects_invalid_confidence_types(threshold) -> None:
    with pytest.raises(ValueError, match="minimum_confidence"):
        selective_predictions([[0.8, 0.2]], minimum_confidence=threshold)


@pytest.mark.parametrize("coverage", [True, False, "0.8", float("nan"), float("inf"), 0])
def test_coverage_selection_rejects_invalid_coverage_types(coverage) -> None:
    with pytest.raises(ValueError, match="minimum_coverage"):
        select_threshold_for_coverage([[0.8, 0.2]], minimum_coverage=coverage)


def test_probability_validation_rejects_overflowed_row_sum() -> None:
    with pytest.raises(ValueError, match="positive finite sum"):
        fit_temperature([[1e308, 1e308]], [0])
