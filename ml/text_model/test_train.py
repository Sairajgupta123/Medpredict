"""Unit tests for text dataset validation, splitting and evaluation helpers."""

import pandas as pd
import pytest

from ml.text_model.train import load_dataset, split_dataset


def test_dataset_rejects_missing_columns(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"text": ["fever"], "label": ["condition"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing required columns"):
        load_dataset(path)


def test_dataset_rejects_classes_with_one_row(tmp_path) -> None:
    path = tmp_path / "rare.csv"
    pd.DataFrame(
        {
            "symptom_text": ["fever", "cough", "rash"],
            "condition_label": ["A", "A", "B"],
        }
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="at least two rows"):
        load_dataset(path)


def test_group_split_keeps_groups_separate() -> None:
    frame = pd.DataFrame(
        {
            "symptom_text": [f"symptom text {i}" for i in range(12)],
            "condition_label": ["A"] * 6 + ["B"] * 6,
            "group_id": [f"a-{i}" for i in range(6)] + [f"b-{i}" for i in range(6)],
        }
    )
    train, test, method = split_dataset(frame, test_size=0.33, random_state=4)
    assert method == "group_shuffle_split"
    assert set(train["group_id"]).isdisjoint(set(test["group_id"]))


def test_group_split_rejects_missing_group_identifiers() -> None:
    frame = pd.DataFrame(
        {
            "symptom_text": ["one", "two", "three", "four"],
            "condition_label": ["A", "A", "B", "B"],
            "group_id": ["1", "", "3", "4"],
        }
    )
    with pytest.raises(ValueError, match="blank values"):
        split_dataset(frame, test_size=0.25, random_state=1)
