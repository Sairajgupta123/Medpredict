"""Patient-grouped, class-aware splits for skin-image research manifests.

Every patient stays in exactly one partition. A deterministic candidate search prefers the
requested row/patient proportions and label distributions while requiring every class to occur
in train, validation and test. If the manifest cannot support that requirement, splitting fails
rather than silently producing incomplete class metrics.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit


@dataclass(frozen=True)
class SplitIndices:
    train: tuple[int, ...]
    validation: tuple[int, ...]
    test: tuple[int, ...]


def _partition_score(
    partitions: tuple[np.ndarray, np.ndarray, np.ndarray],
    labels: np.ndarray,
    groups: np.ndarray,
    target_fractions: tuple[float, float, float],
    class_count: int,
) -> float | None:
    """Score a candidate; None means at least one class is absent from a partition."""
    total_rows = len(labels)
    total_groups = len(np.unique(groups))
    overall_distribution = np.bincount(labels, minlength=class_count) / total_rows
    score = 0.0

    for positions, target_fraction in zip(partitions, target_fractions):
        if len(positions) == 0:
            return None
        partition_labels = labels[positions]
        counts = np.bincount(partition_labels, minlength=class_count)
        if (counts == 0).any():
            return None

        row_fraction = len(positions) / total_rows
        group_fraction = len(np.unique(groups[positions])) / total_groups
        distribution = counts / counts.sum()

        # Row proportions matter for training volume; group proportions matter for independence.
        score += abs(row_fraction - target_fraction)
        score += 0.5 * abs(group_fraction - target_fraction)
        # Total variation distance penalizes class distributions unlike the full dataset.
        score += 2.0 * float(np.abs(distribution - overall_distribution).sum() / 2.0)

    return float(score)


def patient_grouped_split(
    manifest: pd.DataFrame,
    *,
    patient_column: str = "patient_id",
    label_column: str = "label",
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
    test_fraction: float = 0.15,
    random_state: int = 42,
    search_attempts: int = 64,
) -> SplitIndices:
    """Create a deterministic class-aware split without patient overlap."""
    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(not np.isfinite(value) or value <= 0 or value >= 1 for value in fractions):
        raise ValueError("Each split fraction must be between 0 and 1")
    if abs(sum(fractions) - 1.0) > 1e-8:
        raise ValueError("Split fractions must sum to 1")
    if search_attempts < 1:
        raise ValueError("search_attempts must be at least 1")
    missing_columns = {patient_column, label_column} - set(manifest.columns)
    if missing_columns:
        raise ValueError(
            f"Required split columns are missing: {sorted(missing_columns)}"
        )
    if manifest.empty:
        raise ValueError("Cannot split an empty manifest")

    group_series = manifest[patient_column].fillna("").astype(str).str.strip()
    label_series = manifest[label_column].fillna("").astype(str).str.strip()
    if group_series.eq("").any():
        raise ValueError("Every row must have a nonblank patient grouping identifier")
    if label_series.eq("").any():
        raise ValueError("Every row must have a nonblank class label")

    unique_groups = group_series.nunique()
    if unique_groups < 3:
        raise ValueError("At least three distinct patients are required for three splits")

    labels, class_names = pd.factorize(label_series, sort=True)
    if len(class_names) < 2:
        raise ValueError("At least two distinct classes are required for a classification split")
    groups = group_series.to_numpy()
    class_group_counts = (
        pd.DataFrame({"label": labels, "group": groups})
        .drop_duplicates()
        .groupby("label")["group"]
        .nunique()
    )
    insufficient = [
        str(class_names[index])
        for index in range(len(class_names))
        if int(class_group_counts.get(index, 0)) < 3
    ]
    if insufficient:
        raise ValueError(
            "Every class must occur in at least three distinct patients to appear in "
            f"all partitions; insufficient patient support for: {insufficient}"
        )

    target_fractions = (train_fraction, validation_fraction, test_fraction)
    relative_validation_fraction = validation_fraction / (
        train_fraction + validation_fraction
    )
    outer_splitter = GroupShuffleSplit(
        n_splits=search_attempts,
        test_size=test_fraction,
        random_state=random_state,
    )
    best_score: float | None = None
    best_positions: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
    dummy_x = np.zeros(len(manifest), dtype=np.uint8)

    for outer_index, (train_validation_pos, test_pos) in enumerate(
        outer_splitter.split(dummy_x, labels, groups)
    ):
        train_validation_groups = groups[train_validation_pos]
        if len(np.unique(train_validation_groups)) < 2:
            continue

        inner_splitter = GroupShuffleSplit(
            n_splits=search_attempts,
            test_size=relative_validation_fraction,
            random_state=random_state + outer_index + 1,
        )
        inner_x = np.zeros(len(train_validation_pos), dtype=np.uint8)
        for train_relative, validation_relative in inner_splitter.split(
            inner_x,
            labels[train_validation_pos],
            train_validation_groups,
        ):
            train_pos = train_validation_pos[train_relative]
            validation_pos = train_validation_pos[validation_relative]
            partitions = (train_pos, validation_pos, test_pos)
            score = _partition_score(
                partitions,
                labels,
                groups,
                target_fractions,
                len(class_names),
            )
            if score is not None and (best_score is None or score < best_score):
                best_score = score
                best_positions = partitions

    if best_positions is None:
        support = {
            str(class_names[index]): int(class_group_counts.get(index, 0))
            for index in range(len(class_names))
        }
        raise ValueError(
            "Could not create train/validation/test partitions containing every class. "
            "Review patient-level class support and dataset size. "
            f"Distinct patients per class: {support}"
        )

    row_indices = manifest.index.to_numpy()
    train_indices, validation_indices, test_indices = (
        tuple(int(row_indices[position]) for position in positions)
        for positions in best_positions
    )

    train_groups = set(group_series.loc[list(train_indices)])
    validation_groups = set(group_series.loc[list(validation_indices)])
    test_groups = set(group_series.loc[list(test_indices)])
    if (
        train_groups & validation_groups
        or train_groups & test_groups
        or validation_groups & test_groups
    ):
        raise RuntimeError("Patient leakage detected across generated partitions")

    return SplitIndices(
        train=train_indices,
        validation=validation_indices,
        test=test_indices,
    )
