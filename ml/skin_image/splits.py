"""Patient-grouped splits for skin-image research manifests.

The helper refuses row-level splitting and requires a nonblank patient identifier for every
included row. It returns manifest row indices only; callers must keep identifiers private.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit


@dataclass(frozen=True)
class SplitIndices:
    train: tuple[int, ...]
    validation: tuple[int, ...]
    test: tuple[int, ...]


def patient_grouped_split(
    manifest: pd.DataFrame,
    *,
    patient_column: str = "patient_id",
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
    test_fraction: float = 0.15,
    random_state: int = 42,
) -> SplitIndices:
    """Split by patient, ensuring no patient can appear in multiple partitions."""
    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(value <= 0 or value >= 1 for value in fractions):
        raise ValueError("Each split fraction must be between 0 and 1")
    if abs(sum(fractions) - 1.0) > 1e-8:
        raise ValueError("Split fractions must sum to 1")
    if patient_column not in manifest.columns:
        raise ValueError(f"Required patient grouping column is missing: {patient_column}")
    if manifest.empty:
        raise ValueError("Cannot split an empty manifest")

    groups = manifest[patient_column].fillna("").astype(str).str.strip()
    if groups.eq("").any():
        raise ValueError("Every row must have a nonblank patient grouping identifier")
    unique_groups = groups.nunique()
    if unique_groups < 3:
        raise ValueError("At least three distinct patients are required for three splits")

    row_indices = manifest.index.to_numpy()
    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=test_fraction,
        random_state=random_state,
    )
    train_validation_pos, test_pos = next(
        splitter.split(row_indices, groups=groups.to_numpy())
    )

    train_validation_groups = groups.iloc[train_validation_pos]
    relative_validation_fraction = validation_fraction / (
        train_fraction + validation_fraction
    )
    if train_validation_groups.nunique() < 2:
        raise ValueError("Not enough training patients to create train/validation splits")

    second_splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=relative_validation_fraction,
        random_state=random_state,
    )
    train_relative, validation_relative = next(
        second_splitter.split(
            row_indices[train_validation_pos],
            groups=train_validation_groups.to_numpy(),
        )
    )
    train_pos = train_validation_pos[train_relative]
    validation_pos = train_validation_pos[validation_relative]

    train_indices = tuple(int(row_indices[position]) for position in train_pos)
    validation_indices = tuple(
        int(row_indices[position]) for position in validation_pos
    )
    test_indices = tuple(int(row_indices[position]) for position in test_pos)

    # Defensive assertion: this is the central leakage-prevention guarantee.
    train_groups = set(groups.loc[list(train_indices)])
    validation_groups = set(groups.loc[list(validation_indices)])
    test_groups = set(groups.loc[list(test_indices)])
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
