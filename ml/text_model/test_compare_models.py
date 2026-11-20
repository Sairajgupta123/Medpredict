"""Tests for text-model comparison input validation."""

import pytest

from ml.text_model.compare_models import compare_text_models


def test_comparison_rejects_invalid_test_fraction(tmp_path) -> None:
    with pytest.raises(ValueError, match="test_size"):
        compare_text_models(
            tmp_path / "missing.csv",
            tmp_path / "out",
            test_size=0.01,
        )


def test_default_candidates_include_logistic_regression_and_random_forest() -> None:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    from ml.text_model.compare_models import _candidates

    candidates = _candidates(random_state=17, include_xgboost=False)
    assert set(candidates) == {"logistic_regression", "random_forest"}
    assert isinstance(candidates["logistic_regression"], LogisticRegression)
    assert isinstance(candidates["random_forest"], RandomForestClassifier)
    assert candidates["logistic_regression"].class_weight == "balanced"
    assert candidates["random_forest"].class_weight == "balanced_subsample"

@pytest.mark.parametrize("value", [True, False, "0.2", float("nan"), float("inf")])
def test_comparison_rejects_invalid_partition_fraction_types(tmp_path, value) -> None:
    with pytest.raises(ValueError, match="test_size"):
        compare_text_models(
            tmp_path / "missing.csv",
            tmp_path / "out",
            test_size=value,
        )


@pytest.mark.parametrize("value", [True, "0.9", float("nan"), float("inf"), 0])
def test_comparison_rejects_invalid_validation_coverage_types(tmp_path, value) -> None:
    with pytest.raises(ValueError, match="target_validation_coverage"):
        compare_text_models(
            tmp_path / "missing.csv",
            tmp_path / "out",
            target_validation_coverage=value,
        )


@pytest.mark.parametrize("value", [True, "0.5", float("nan"), float("inf")])
def test_comparison_rejects_invalid_explicit_confidence_types(tmp_path, value) -> None:
    with pytest.raises(ValueError, match="minimum_confidence"):
        compare_text_models(
            tmp_path / "missing.csv",
            tmp_path / "out",
            minimum_confidence=value,
        )
