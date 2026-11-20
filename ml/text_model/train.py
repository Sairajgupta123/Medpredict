"""Train and evaluate a research-only symptom-text baseline.

Expected CSV columns:
- symptom_text: free-text symptom description
- condition_label: normalized condition class
- group_id (optional for exploration, required for trustworthy final evaluation):
  patient/source record grouping key to avoid related rows crossing train/test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline


REQUIRED_COLUMNS = {"symptom_text", "condition_label"}


def load_dataset(path: Path) -> pd.DataFrame:
    """Load and validate the minimum dataset contract."""
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file does not exist: {path}")

    frame = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

    frame = frame.copy()
    frame["symptom_text"] = frame["symptom_text"].fillna("").astype(str).str.strip()
    frame["condition_label"] = frame["condition_label"].fillna("").astype(str).str.strip()
    frame = frame[
        frame["symptom_text"].ne("") & frame["condition_label"].ne("")
    ].reset_index(drop=True)

    if frame.empty:
        raise ValueError("No usable rows remain after removing blank text/labels.")

    label_counts = frame["condition_label"].value_counts()
    too_rare = label_counts[label_counts < 2]
    if not too_rare.empty:
        raise ValueError(
            "Every class needs at least two rows for a held-out split. "
            f"Classes with insufficient rows: {too_rare.to_dict()}"
        )

    if frame["condition_label"].nunique() < 2:
        raise ValueError("At least two distinct condition labels are required.")

    return frame


def _group_split(
    frame: pd.DataFrame,
    groups: pd.Series,
    test_size: float,
    random_state: int,
    method: str,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Split without allowing the same group to cross train and test."""
    if groups.eq("").any():
        raise ValueError("Grouping values contain blanks; resolve them before splitting.")
    if groups.nunique() < 2:
        raise ValueError("At least two distinct groups are required for group splitting.")

    splitter = GroupShuffleSplit(
        n_splits=1, test_size=test_size, random_state=random_state
    )
    train_indices, test_indices = next(
        splitter.split(frame, frame["condition_label"], groups)
    )
    train_frame = frame.iloc[train_indices].copy()
    test_frame = frame.iloc[test_indices].copy()
    expected_labels = set(frame["condition_label"])
    if set(train_frame["condition_label"]) != expected_labels:
        raise ValueError(
            "The group split left at least one class out of training. "
            "Review group distribution or collect more representative examples."
        )
    if set(test_frame["condition_label"]) != expected_labels:
        raise ValueError(
            "The group split left at least one class out of testing. "
            "Collect more independent groups per class or redesign the split."
        )
    return train_frame, test_frame, method


def split_dataset(
    frame: pd.DataFrame, test_size: float, random_state: int
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Prefer source groups, then duplicate-text groups, before row splitting."""
    if "group_id" in frame.columns:
        groups = frame["group_id"].fillna("").astype(str).str.strip()
        return _group_split(
            frame, groups, test_size, random_state, "group_shuffle_split"
        )

    normalized_text = (
        frame["symptom_text"]
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )
    if normalized_text.duplicated(keep=False).any():
        warnings.warn(
            "No group_id found. Repeated normalized symptom descriptions are kept "
            "in one partition, but patient/source leakage cannot be ruled out.",
            RuntimeWarning,
            stacklevel=2,
        )
        return _group_split(
            frame,
            normalized_text,
            test_size,
            random_state,
            "normalized_text_group_split_provisional",
        )

    warnings.warn(
        "No group_id or repeated normalized descriptions found. Using a stratified "
        "row split for exploration only; patient/source leakage cannot be ruled out.",
        RuntimeWarning,
        stacklevel=2,
    )
    train_frame, test_frame = train_test_split(
        frame,
        test_size=test_size,
        random_state=random_state,
        stratify=frame["condition_label"],
    )
    return train_frame.copy(), test_frame.copy(), "stratified_row_split_provisional"


def build_pipeline() -> Pipeline:
    """Build a transparent, reproducible TF-IDF + Logistic Regression baseline."""
    features = FeatureUnion(
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
    classifier = LogisticRegression(
        max_iter=2_000,
        class_weight="balanced",
        solver="liblinear",
        random_state=42,
    )
    return Pipeline([("features", features), ("classifier", classifier)])


def evaluate(
    model: Pipeline, x_test: pd.Series, y_test: pd.Series
) -> dict[str, Any]:
    """Compute imbalance-aware held-out metrics."""
    predictions = model.predict(x_test)
    labels = sorted(y_test.unique().tolist())
    report = classification_report(
        y_test,
        predictions,
        labels=labels,
        output_dict=True,
        zero_division=0,
    )
    return {
        "sample_count": int(len(y_test)),
        "class_labels": labels,
        "macro_f1": float(f1_score(y_test, predictions, average="macro")),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, predictions)),
        "classification_report": report,
        "confusion_matrix": confusion_matrix(
            y_test, predictions, labels=labels
        ).tolist(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Reviewed CSV dataset")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ml/artifacts/text_baseline"),
        help="Local output directory (ignored by Git)",
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0.1 <= args.test_size <= 0.4:
        raise ValueError("--test-size must be between 0.1 and 0.4.")

    frame = load_dataset(args.data)
    train_frame, test_frame, split_method = split_dataset(
        frame, args.test_size, args.random_state
    )

    model = build_pipeline()
    model.fit(train_frame["symptom_text"], train_frame["condition_label"])
    metrics = evaluate(model, test_frame["symptom_text"], test_frame["condition_label"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.output_dir / "model.joblib"
    metrics_path = args.output_dir / "metrics.json"

    joblib.dump(model, model_path)
    dataset_hash = hashlib.sha256(args.data.read_bytes()).hexdigest()
    metrics_payload = {
        "purpose": "research_baseline_not_for_clinical_use",
        "dataset_file_name": args.data.name,
        "dataset_sha256": dataset_hash,
        "dataset_rows_after_validation": int(len(frame)),
        "class_count": int(frame["condition_label"].nunique()),
        "split_method": split_method,
        "random_state": args.random_state,
        "test_size": args.test_size,
        "train_rows": int(len(train_frame)),
        "test_rows": int(len(test_frame)),
        "library_versions": {
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "metrics": metrics,
    }
    metrics_path.write_text(
        json.dumps(metrics_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Research model saved to: {model_path}")
    print(f"Evaluation metrics saved to: {metrics_path}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
