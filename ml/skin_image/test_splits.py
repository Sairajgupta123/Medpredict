"""Tests for deterministic patient-grouped skin-image data partitions."""

import pandas as pd
import pytest

from ml.skin_image.splits import patient_grouped_split


def _balanced_manifest(patients_per_class: int = 12) -> pd.DataFrame:
    rows = []
    for label in ("class_a", "class_b"):
        for patient_index in range(patients_per_class):
            patient_id = f"{label}-patient-{patient_index}"
            for image_index in range(2):
                rows.append(
                    {
                        "image_path": f"{patient_id}-{image_index}.jpg",
                        "label": label,
                        "patient_id": patient_id,
                    }
                )
    return pd.DataFrame(rows)


def test_split_is_deterministic_patient_disjoint_and_class_complete() -> None:
    manifest = _balanced_manifest()
    first = patient_grouped_split(manifest, random_state=17, search_attempts=32)
    second = patient_grouped_split(manifest, random_state=17, search_attempts=32)

    assert first == second
    partitions = {
        "train": set(first.train),
        "validation": set(first.validation),
        "test": set(first.test),
    }
    assert partitions["train"].isdisjoint(partitions["validation"])
    assert partitions["train"].isdisjoint(partitions["test"])
    assert partitions["validation"].isdisjoint(partitions["test"])
    assert set.union(*partitions.values()) == set(manifest.index)

    patient_sets = {
        name: set(manifest.loc[list(indices), "patient_id"])
        for name, indices in (
            ("train", first.train),
            ("validation", first.validation),
            ("test", first.test),
        )
    }
    assert patient_sets["train"].isdisjoint(patient_sets["validation"])
    assert patient_sets["train"].isdisjoint(patient_sets["test"])
    assert patient_sets["validation"].isdisjoint(patient_sets["test"])

    for indices in (first.train, first.validation, first.test):
        assert set(manifest.loc[list(indices), "label"]) == {"class_a", "class_b"}


def test_split_rejects_class_with_fewer_than_three_patients() -> None:
    manifest = pd.DataFrame(
        {
            "image_path": ["a.jpg", "b.jpg", "c.jpg", "d.jpg"],
            "label": ["class_a", "class_a", "class_b", "class_b"],
            "patient_id": ["p1", "p2", "p3", "p4"],
        }
    )
    with pytest.raises(ValueError, match="at least three distinct patients"):
        patient_grouped_split(manifest)


def test_split_rejects_single_class_dataset() -> None:
    manifest = pd.DataFrame(
        {
            "image_path": [f"{i}.jpg" for i in range(6)],
            "label": ["class_a"] * 6,
            "patient_id": [f"p{i}" for i in range(6)],
        }
    )
    with pytest.raises(ValueError, match="At least two distinct classes"):
        patient_grouped_split(manifest)


def test_split_rejects_blank_patient_and_label_values() -> None:
    manifest = _balanced_manifest()
    manifest.loc[0, "patient_id"] = " "
    with pytest.raises(ValueError, match="nonblank patient"):
        patient_grouped_split(manifest)

    manifest = _balanced_manifest()
    manifest.loc[0, "label"] = ""
    with pytest.raises(ValueError, match="nonblank class label"):
        patient_grouped_split(manifest)


def test_split_rejects_invalid_fractions() -> None:
    manifest = _balanced_manifest()
    with pytest.raises(ValueError, match="sum to 1"):
        patient_grouped_split(
            manifest,
            train_fraction=0.6,
            validation_fraction=0.2,
            test_fraction=0.3,
        )
