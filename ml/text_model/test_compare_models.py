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

def test_comparison_refuses_to_overwrite_existing_report_before_loading_data(tmp_path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    report = output / "comparison_report.json"
    report.write_text('{"preserve": true}', encoding="utf-8")

    with pytest.raises(FileExistsError, match="comparison_report.json"):
        compare_text_models(
            tmp_path / "missing.csv",
            output,
        )

    assert report.read_text(encoding="utf-8") == '{"preserve": true}'

def test_comparison_uses_shared_stable_experiment_config_digest() -> None:
    from ml.text_model.train import experiment_config_sha256

    config = {
        "pipeline": "tfidf_word_char_candidate_comparison",
        "random_state": 42,
        "test_size": 0.2,
    }
    assert len(experiment_config_sha256(config)) == 64
    assert experiment_config_sha256(config) == experiment_config_sha256(
        {"test_size": 0.2, "random_state": 42, "pipeline": "tfidf_word_char_candidate_comparison"}
    )
