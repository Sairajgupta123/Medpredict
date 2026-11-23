"""Three-way symptom-text model selection and final evaluation.

Candidate selection and temperature calibration use validation data only. The final test
partition is evaluated once after a winner has been frozen. XGBoost is optional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion
from sklearn.preprocessing import LabelEncoder

from ml.text_model.calibration import (
    apply_temperature,
    calibration_metrics,
    fit_temperature,
    select_threshold_for_coverage,
)
from ml.text_model.metrics import evaluate_predictions
from ml.text_model.inference import validate_text_model_bundle
from ml.text_model.train import (
    ensure_artifacts_do_not_exist,
    experiment_config_sha256,
    load_dataset,
    split_dataset_three_way,
)


def build_feature_union() -> FeatureUnion:
    """Create word and character TF-IDF features fitted on training text only."""
    return FeatureUnion(
        [
            ("word", TfidfVectorizer(
                analyzer="word", ngram_range=(1, 2), lowercase=True,
                strip_accents="unicode", sublinear_tf=True, max_features=100_000,
            )),
            ("char", TfidfVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), lowercase=True,
                sublinear_tf=True, max_features=100_000,
            )),
        ]
    )


def _candidates(random_state: int, include_xgboost: bool) -> dict[str, Any]:
    candidates: dict[str, Any] = {
        "logistic_regression": LogisticRegression(
            max_iter=2_000, class_weight="balanced", solver="lbfgs",
            random_state=random_state,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=300, class_weight="balanced_subsample",
            max_features="sqrt", random_state=random_state, n_jobs=-1,
        ),
    }
    if include_xgboost:
        try:
            from xgboost import XGBClassifier
        except ImportError as exc:
            raise RuntimeError(
                "XGBoost is optional. Install ml/requirements-text-boosted.txt "
                "or rerun without --include-xgboost."
            ) from exc
        candidates["xgboost"] = XGBClassifier(
            objective="multi:softprob", eval_metric="mlogloss",
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.9, colsample_bytree=0.9, tree_method="hist",
            random_state=random_state, n_jobs=-1,
        )
    return candidates


def _encoded_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    labels: list[str],
) -> dict[str, Any]:
    return evaluate_predictions(actual, predicted, class_labels=labels)


def compare_text_models(
    data_path: Path,
    output_dir: Path,
    *,
    test_size: float = 0.2,
    validation_size: float = 0.2,
    random_state: int = 42,
    include_xgboost: bool = False,
    minimum_confidence: float | None = None,
    target_validation_coverage: float = 0.9,
) -> dict[str, Any]:
    """Select on validation macro-F1, calibrate on validation, test winner once."""
    def validate_fraction(value: Any, name: str, lower: float, upper: float) -> float:
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, float, np.integer, np.floating))
            or not np.isfinite(value)
            or not lower <= value <= upper
        ):
            raise ValueError(f"{name} must be a finite number between {lower} and {upper}")
        return float(value)

    test_size = validate_fraction(test_size, "test_size", 0.05, 0.4)
    validation_size = validate_fraction(
        validation_size, "validation_size", 0.05, 0.4
    )
    if test_size + validation_size >= 0.8:
        raise ValueError("test_size + validation_size must be below 0.8")
    if minimum_confidence is not None:
        minimum_confidence = validate_fraction(
            minimum_confidence, "minimum_confidence", 0.0, 1.0
        )
    target_validation_coverage = validate_fraction(
        target_validation_coverage, "target_validation_coverage", 0.0, 1.0
    )
    if target_validation_coverage == 0:
        raise ValueError("target_validation_coverage must be in (0, 1]")

    ensure_artifacts_do_not_exist(
        output_dir,
        [
            "comparison_report.json",
            "logistic_regression_selected.joblib",
            "random_forest_selected.joblib",
            "xgboost_selected.joblib",
            "artifact_manifest.json",
        ],
    )
    frame = load_dataset(data_path)
    train_frame, validation_frame, test_frame, split_methods = (
        split_dataset_three_way(
            frame,
            test_size=test_size,
            validation_size=validation_size,
            random_state=random_state,
        )
    )

    encoder = LabelEncoder()
    y_train = encoder.fit_transform(train_frame["condition_label"])
    y_validation = encoder.transform(validation_frame["condition_label"])
    y_test = encoder.transform(test_frame["condition_label"])
    class_labels = encoder.classes_.tolist()

    vectorizer = build_feature_union()
    x_train = vectorizer.fit_transform(train_frame["symptom_text"])
    x_validation = vectorizer.transform(validation_frame["symptom_text"])
    x_test = vectorizer.transform(test_frame["symptom_text"])

    output_dir.mkdir(parents=True, exist_ok=True)
    fitted: dict[str, Any] = {}
    validation_results: list[dict[str, Any]] = []
    for name, estimator in _candidates(random_state, include_xgboost).items():
        estimator.fit(x_train, y_train)
        validation_predictions = np.asarray(
            estimator.predict(x_validation), dtype=np.int64
        )
        metrics = _encoded_metrics(
            y_validation, validation_predictions, class_labels
        )
        fitted[name] = estimator
        validation_results.append(
            {
                "model": name,
                "validation_macro_f1": metrics["macro_f1"],
                "validation_balanced_accuracy": metrics["balanced_accuracy"],
                "validation_metrics": metrics,
            }
        )

    validation_results.sort(
        key=lambda item: item["validation_macro_f1"], reverse=True
    )
    winner_name = validation_results[0]["model"]
    winner = fitted[winner_name]

    # Calibration is fitted only from the selected model's validation probabilities.
    validation_probabilities = winner.predict_proba(x_validation)
    temperature = fit_temperature(validation_probabilities, y_validation)
    calibrated_validation = apply_temperature(
        validation_probabilities, temperature=temperature
    )
    if minimum_confidence is None:
        threshold_selection = select_threshold_for_coverage(
            validation_probabilities,
            minimum_coverage=target_validation_coverage,
            temperature=temperature,
        )
        selected_threshold = threshold_selection["threshold"]
    else:
        selected_threshold = float(minimum_confidence)
        validation_threshold_coverage = float(
            np.mean(calibrated_validation.max(axis=1) >= selected_threshold)
        )
        threshold_selection = {
            "minimum_coverage_target": None,
            "threshold": selected_threshold,
            "achieved_validation_coverage": validation_threshold_coverage,
            "validation_sample_count": int(len(y_validation)),
            "note": "Explicit caller threshold; validate independently.",
        }
    validation_calibration = calibration_metrics(
        validation_probabilities, y_validation, temperature=temperature
    )

    # The final test partition is accessed only after candidate and calibration choices freeze.
    test_probabilities = winner.predict_proba(x_test)
    test_raw_predictions = np.asarray(winner.predict(x_test), dtype=np.int64)
    calibrated_test = apply_temperature(
        test_probabilities, temperature=temperature
    )
    test_calibrated_predictions = calibrated_test.argmax(axis=1)
    test_metrics_raw = _encoded_metrics(
        y_test, test_raw_predictions, class_labels
    )
    test_metrics_calibrated = _encoded_metrics(
        y_test, test_calibrated_predictions, class_labels
    )
    test_calibration = calibration_metrics(
        test_probabilities, y_test, temperature=temperature
    )

    confidence = calibrated_test.max(axis=1)
    selective_labels = [
        int(label) if score >= selected_threshold else None
        for label, score in zip(
            test_calibrated_predictions, confidence, strict=True
        )
    ]
    accepted = np.asarray([label is not None for label in selective_labels])
    selective_coverage = float(accepted.mean())
    selective_metrics = (
        _encoded_metrics(
            y_test[accepted],
            np.asarray([label for label in selective_labels if label is not None]),
            class_labels,
        )
        if accepted.any()
        else None
    )

    dataset_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
    bundle = {
        "vectorizer": vectorizer,
        "estimator": winner,
        "label_encoder": encoder,
        "model_name": winner_name,
        "temperature": temperature,
        "minimum_confidence": selected_threshold,
        "class_labels": class_labels,
        "purpose": "research_only_not_for_clinical_use",
    }
    validate_text_model_bundle(bundle)
    artifact_path = output_dir / f"{winner_name}_selected.joblib"
    joblib.dump(bundle, artifact_path)
    artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    artifact_manifest = {
        "purpose": "research_only_not_for_clinical_use",
        "artifact_file": artifact_path.name,
        "artifact_sha256": artifact_sha256,
        "model_name": winner_name,
        "dataset_sha256": dataset_hash,
        "experiment_config_sha256": experiment_config_sha256({
            "pipeline": "tfidf_word_char_candidate_comparison",
            "candidate_models": list(fitted.keys()),
            "random_state": random_state,
            "test_size": test_size,
            "validation_size": validation_size,
        }),
        "integrity_note": "SHA-256 detects accidental or uncoordinated file changes; it is not a digital signature and does not establish artifact authenticity.",
    }
    (output_dir / "artifact_manifest.json").write_text(
        json.dumps(artifact_manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    experiment_config = {
        "pipeline": "tfidf_word_char_candidate_comparison",
        "feature_extraction": {
            "word_ngram_range": [1, 2],
            "character_ngram_range": [3, 5],
            "max_features_per_vectorizer": 100_000,
        },
        "candidate_models": list(fitted.keys()),
        "candidate_parameters": {
            name: estimator.get_params(deep=False)
            for name, estimator in fitted.items()
        },
        "include_xgboost": include_xgboost,
        "selection_metric": "validation_macro_f1",
        "random_state": random_state,
        "test_size": test_size,
        "validation_size": validation_size,
        "split_methods": split_methods,
        "calibration_method": "scalar_temperature_scaling",
        "minimum_confidence": minimum_confidence,
        "target_validation_coverage": target_validation_coverage,
        "threshold_source": (
            "validation_target_coverage"
            if minimum_confidence is None
            else "explicit_caller_value"
        ),
    }
    summary = {
        "purpose": "research_three_way_evaluation_not_for_clinical_use",
        "experiment_config": experiment_config,
        "experiment_config_sha256": experiment_config_sha256(experiment_config),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "dataset_file_name": data_path.name,
        "dataset_sha256": dataset_hash,
        "dataset_rows_after_validation": int(len(frame)),
        "partition_rows": {
            "train": int(len(train_frame)),
            "validation": int(len(validation_frame)),
            "test": int(len(test_frame)),
        },
        "class_labels": class_labels,
        "split_methods": split_methods,
        "random_state": random_state,
        "test_size": test_size,
        "validation_size": validation_size,
        "selection_metric": "validation_macro_f1",
        "selected_model": winner_name,
        "validation_candidate_results": validation_results,
        "calibration": {
            "method": "scalar_temperature_scaling",
            "temperature": temperature,
            "fit_partition": "validation",
            "validation_metrics": validation_calibration,
        },
        "final_test_metrics": {
            "raw": test_metrics_raw,
            "calibrated": test_metrics_calibrated,
            "calibration": test_calibration,
        },
        "selective_prediction": {
            "minimum_confidence": selected_threshold,
            "threshold_selection": threshold_selection,
            "threshold_source": (
                "validation_target_coverage"
                if minimum_confidence is None
                else "explicit_caller_value"
            ),
            "coverage": selective_coverage,
            "accepted_count": int(accepted.sum()),
            "sample_count": int(len(accepted)),
            "accepted_subset_metrics": selective_metrics,
            "note": (
                "The threshold is a research setting. Select it using validation data "
                "and report the resulting coverage-risk trade-off on an untouched cohort."
            ),
        },
        "artifact_file": artifact_path.name,
        "artifact_sha256": artifact_sha256,
        "artifact_manifest_file": "artifact_manifest.json",
        "library_versions": {
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "warnings": [
            "No clinical validation or deployment approval is implied.",
            "When group_id is absent, split methods are explicitly provisional.",
            "A model score is not a disease probability or medical certainty.",
            "Review class support, false negatives, calibration and subgroup performance.",
        ],
    }
    (output_dir / "comparison_report.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("ml/artifacts/text_comparison")
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--validation-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--include-xgboost", action="store_true")
    parser.add_argument(
        "--minimum-confidence",
        type=float,
        default=None,
        help="Optional explicit threshold; by default derive a cutoff from validation coverage.",
    )
    parser.add_argument("--target-validation-coverage", type=float, default=0.9)
    args = parser.parse_args()
    result = compare_text_models(
        args.data,
        args.output_dir,
        test_size=args.test_size,
        validation_size=args.validation_size,
        random_state=args.random_state,
        include_xgboost=args.include_xgboost,
        minimum_confidence=args.minimum_confidence,
        target_validation_coverage=args.target_validation_coverage,
    )
    print(json.dumps({
        "status": result["purpose"],
        "selected_model": result["selected_model"],
        "selection_metric": result["selection_metric"],
        "report_file": str(args.output_dir / "comparison_report.json"),
    }, indent=2))


if __name__ == "__main__":
    main()
