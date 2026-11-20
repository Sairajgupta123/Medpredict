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
from ml.text_model.metrics import evaluate_predictions
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

    normalized_text = (
        frame["symptom_text"]
        .str.lower()
        .str.replace(r"\\s+", " ", regex=True)
    )
    label_counts_per_description = (
        pd.DataFrame(
            {
                "normalized_text": normalized_text,
                "condition_label": frame["condition_label"],
            }
        )
        .groupby("normalized_text")["condition_label"]
        .nunique()
    )
    conflicting_descriptions = int((label_counts_per_description > 1).sum())
    if conflicting_descriptions:
        raise ValueError(
            "Dataset contains normalized symptom descriptions assigned to "
            f"multiple condition labels ({conflicting_descriptions} conflicts). "
            "Resolve or explicitly review these ambiguous records before training."
        )

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
    """Compute class-aware held-out metrics using the complete model class order."""
    predictions = model.predict(x_test)
    classifier = model.named_steps["classifier"]
    class_labels = [str(label) for label in classifier.classes_]
    label_to_index = {label: index for index, label in enumerate(class_labels)}
    try:
        actual_indices = [label_to_index[str(label)] for label in y_test.tolist()]
        predicted_indices = [label_to_index[str(label)] for label in predictions.tolist()]
    except KeyError as exc:
        raise ValueError("Evaluation label is absent from the fitted model classes") from exc
    return evaluate_predictions(
        actual_indices,
        predicted_indices,
        class_labels=class_labels,
    )


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


def split_dataset_three_way(
    frame: pd.DataFrame,
    *,
    test_size: float = 0.2,
    validation_size: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """Create disjoint train/validation/test partitions with group-aware splitting.

    validation_size and test_size are fractions of the complete dataset.
    """
    if not 0.05 <= test_size <= 0.4:
        raise ValueError("test_size must be between 0.05 and 0.4")
    if not 0.05 <= validation_size <= 0.4:
        raise ValueError("validation_size must be between 0.05 and 0.4")
    if test_size + validation_size >= 0.8:
        raise ValueError("test_size + validation_size must be below 0.8")

    remaining, test_frame, test_method = split_dataset(
        frame, test_size, random_state
    )
    relative_validation_size = validation_size / (1.0 - test_size)
    train_frame, validation_frame, validation_method = split_dataset(
        remaining,
        relative_validation_size,
        random_state + 1,
    )
    expected = set(frame["condition_label"])
    for name, partition in (
        ("training", train_frame),
        ("validation", validation_frame),
        ("test", test_frame),
    ):
        missing = expected - set(partition["condition_label"])
        if missing:
            raise ValueError(
                f"{name} partition is missing classes: {sorted(missing)}. "
                "Collect more independent groups per class or revise the split."
            )

    group_column = "group_id" if "group_id" in frame.columns else None
    if group_column:
        groups = [
            set(partition[group_column].astype(str))
            for partition in (train_frame, validation_frame, test_frame)
        ]
        if (
            groups[0] & groups[1]
            or groups[0] & groups[2]
            or groups[1] & groups[2]
        ):
            raise RuntimeError("A source group crossed partition boundaries")
    return (
        train_frame,
        validation_frame,
        test_frame,
        {
            "train_validation": validation_method,
            "test": test_method,
        },
    )
