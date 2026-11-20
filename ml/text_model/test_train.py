"""Tests for text dataset validation, splitting and evaluation helpers."""

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
    with pytest.raises(ValueError, match="blanks"):
        split_dataset(frame, test_size=0.25, random_state=1)


def test_duplicate_normalized_text_never_crosses_partitions() -> None:
    frame = pd.DataFrame(
        {
            "symptom_text": [
                "Fever and cough", " fever   and cough ",
                "itchy rash", " itchy   rash ",
                "headache", " headache ",
                "joint pain", " joint  pain ",
            ],
            "condition_label": ["A", "A", "A", "A", "B", "B", "B", "B"],
        }
    )
    with pytest.warns(RuntimeWarning, match="No group_id"):
        train, test, method = split_dataset(frame, test_size=0.5, random_state=7)

    assert method == "normalized_text_group_split_provisional"
    normalize = lambda values: values.str.strip().str.lower().str.replace(
        r"\s+", " ", regex=True
    )
    assert set(normalize(train["symptom_text"])).isdisjoint(
        set(normalize(test["symptom_text"]))
    )


def test_unique_text_uses_provisional_stratified_split() -> None:
    frame = pd.DataFrame(
        {
            "symptom_text": [f"unique symptom {i}" for i in range(20)],
            "condition_label": ["A"] * 10 + ["B"] * 10,
        }
    )
    with pytest.warns(RuntimeWarning, match="No group_id"):
        train, test, method = split_dataset(frame, test_size=0.2, random_state=42)

    assert method == "stratified_row_split_provisional"
    assert set(train["condition_label"]) == {"A", "B"}
    assert set(test["condition_label"]) == {"A", "B"}


def test_three_way_group_split_has_disjoint_groups_and_all_classes() -> None:
    from ml.text_model.train import split_dataset_three_way

    frame = pd.DataFrame(
        {
            "symptom_text": [f"symptom {label} {i}" for label in ("A", "B") for i in range(20)],
            "condition_label": [label for label in ("A", "B") for _ in range(20)],
            "group_id": [f"{label}-{i}" for label in ("A", "B") for i in range(20)],
        }
    )
    train, validation, test, methods = split_dataset_three_way(
        frame, test_size=0.2, validation_size=0.2, random_state=19
    )
    groups = [
        set(partition["group_id"])
        for partition in (train, validation, test)
    ]
    assert not (groups[0] & groups[1])
    assert not (groups[0] & groups[2])
    assert not (groups[1] & groups[2])
    for partition in (train, validation, test):
        assert set(partition["condition_label"]) == {"A", "B"}
    assert methods["test"] == "group_shuffle_split"


def test_three_way_split_rejects_invalid_partition_sizes() -> None:
    from ml.text_model.train import split_dataset_three_way

    frame = pd.DataFrame(
        {
            "symptom_text": [f"symptom {i}" for i in range(20)],
            "condition_label": ["A"] * 10 + ["B"] * 10,
        }
    )
    with pytest.raises(ValueError, match="below 0.8"):
        split_dataset_three_way(frame, test_size=0.4, validation_size=0.4)
