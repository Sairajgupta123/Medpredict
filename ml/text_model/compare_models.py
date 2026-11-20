"""Controlled symptom-text model comparison using one shared data split.

All vectorizers are fitted on training text only. Candidate ranking uses held-out macro-F1
for exploratory comparison; do not use the same test set repeatedly for final model selection.
XGBoost is optional and must be explicitly enabled.
"""

from __future__ import annotations

import argparse
import json
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

from ml.text_model.metrics import evaluate_predictions
from ml.text_model.train import load_dataset, split_dataset


def build_feature_union() -> FeatureUnion:
    """Create word and character TF-IDF features without fitting on held-out rows."""
    return FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    lowercase=True,
                    strip_accents="unicode",
                    sublinear_tf=True,
                    max_features=100_000,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    lowercase=True,
                    sublinear_tf=True,
                    max_features=100_000,
                ),
            ),
        ]
    )


def _candidates(random_state: int, include_xgboost: bool) -> dict[str, Any]:
    candidates: dict[str, Any] = {
        "logistic_regression": LogisticRegression(
            max_iter=2_000,
            class_weight="balanced",
            solver="lbfgs",
            random_state=random_state,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            class_weight="balanced_subsample",
            max_features="sqrt",
            random_state=random_state,
            n_jobs=-1,
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
            objective="multi:softprob",
            eval_metric="mlogloss",
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            tree_method="hist",
            random_state=random_state,
            n_jobs=-1,
        )
    return candidates


def compare_text_models(
    data_path: Path,
    output_dir: Path,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
    include_xgboost: bool = False,
) -> dict[str, Any]:
    """Fit candidates on one shared split and save research-only reports/artifacts."""
    if not 0.1 <= test_size <= 0.4:
        raise ValueError("test_size must be between 0.1 and 0.4")
    frame = load_dataset(data_path)
    train_frame, test_frame, split_method = split_dataset(
        frame, test_size, random_state
    )

    encoder = LabelEncoder()
    y_train = encoder.fit_transform(train_frame["condition_label"])
    try:
        y_test = encoder.transform(test_frame["condition_label"])
    except ValueError as exc:
        raise ValueError("Test partition contains a class absent from training") from exc

    vectorizer = build_feature_union()
    x_train = vectorizer.fit_transform(train_frame["symptom_text"])
    x_test = vectorizer.transform(test_frame["symptom_text"])

    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_hash = __import__("hashlib").sha256(data_path.read_bytes()).hexdigest()
    results: list[dict[str, Any]] = []

    for name, estimator in _candidates(random_state, include_xgboost).items():
        estimator.fit(x_train, y_train)
        predictions = np.asarray(estimator.predict(x_test), dtype=np.int64)
        metrics = evaluate_predictions(
            y_test,
            predictions,
            class_labels=encoder.classes_.tolist(),
        )
        bundle = {
            "vectorizer": vectorizer,
            "estimator": estimator,
            "label_encoder": encoder,
            "model_name": name,
            "purpose": "research_only_not_for_clinical_use",
        }
        artifact_path = output_dir / f"{name}.joblib"
        joblib.dump(bundle, artifact_path)
        results.append(
            {
                "model": name,
                "macro_f1": metrics["macro_f1"],
                "balanced_accuracy": metrics["balanced_accuracy"],
                "metrics": metrics,
                "artifact_file": artifact_path.name,
            }
        )

    results.sort(key=lambda item: item["macro_f1"], reverse=True)
    summary = {
        "purpose": "research_comparison_not_for_clinical_use",
        "dataset_file_name": data_path.name,
        "dataset_sha256": dataset_hash,
        "dataset_rows_after_validation": int(len(frame)),
        "train_rows": int(len(train_frame)),
        "test_rows": int(len(test_frame)),
        "class_labels": encoder.classes_.tolist(),
        "split_method": split_method,
        "random_state": random_state,
        "test_size": test_size,
        "ranking_metric": "held_out_macro_f1_exploratory_only",
        "test_set_reused_for_model_comparison": True,
        "warning": (
            "This comparison uses one held-out partition for exploratory ranking. "
            "Do not treat the top score as an unbiased final estimate. After selection, "
            "evaluate the frozen model once on a new untouched external test cohort."
        ),
        "library_versions": {
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "results": results,
    }
    (output_dir / "comparison_report.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("ml/artifacts/text_comparison")
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--include-xgboost", action="store_true")
    args = parser.parse_args()
    result = compare_text_models(
        args.data,
        args.output_dir,
        test_size=args.test_size,
        random_state=args.random_state,
        include_xgboost=args.include_xgboost,
    )
    print(
        json.dumps(
            {
                "status": result["purpose"],
                "models_compared": [item["model"] for item in result["results"]],
                "report_file": str(args.output_dir / "comparison_report.json"),
                "warning": result["warning"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
