"""Tests for validation-fitted temperature scaling and calibration metrics."""

import numpy as np
import pytest

from ml.skin_image.calibration import (
    calibration_metrics,
    fit_temperature,
    multiclass_nll,
)


def test_temperature_is_positive_and_deterministic() -> None:
    logits = np.array([[4.0, 0.0], [0.0, 3.0], [2.0, 0.0], [0.0, 2.0]])
    targets = np.array([0, 1, 1, 0])
    first = fit_temperature(logits, targets)
    second = fit_temperature(logits, targets)
    assert first > 0
    assert first == pytest.approx(second)


def test_temperature_scaling_reduces_validation_nll_when_overconfident() -> None:
    logits = np.array([[8.0, 0.0], [0.0, 8.0], [8.0, 0.0], [0.0, 8.0]])
    targets = np.array([0, 1, 1, 0])
    temperature = fit_temperature(logits, targets)
    assert multiclass_nll(logits, targets, temperature=temperature) <= (
        multiclass_nll(logits, targets)
    )


def test_calibration_metrics_return_expected_fields() -> None:
    result = calibration_metrics(
        [[2.0, 0.0], [0.0, 2.0]],
        [0, 1],
        temperature=1.2,
        bins=5,
    )
    assert result["sample_count"] == 2
    assert result["temperature"] == pytest.approx(1.2)
    assert 0 <= result["top_label_ece"] <= 1
    assert 0 <= result["multiclass_brier_score"] <= 2


def test_calibration_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="positive finite"):
        multiclass_nll([[1.0, 0.0]], [0], temperature=0)
    with pytest.raises(ValueError, match="integer class indices"):
        fit_temperature([[1.0, 0.0]], [0.5])
    with pytest.raises(ValueError, match="outside"):
        calibration_metrics([[1.0, 0.0]], [2])

def test_calibration_metrics_reject_non_integer_bin_counts() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        calibration_metrics([[1.0, 0.0]], [0], bins=1.5)
    with pytest.raises(ValueError, match="positive integer"):
        calibration_metrics([[1.0, 0.0]], [0], bins=True)

@pytest.mark.parametrize("temperature", [True, float("nan"), float("inf"), "hot"])
def test_calibration_rejects_invalid_temperature_types(temperature: object) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        multiclass_nll([[1.0, 0.0]], [0], temperature=temperature)
