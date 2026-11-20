"""Tests for skin image preprocessing and patient-level splitting."""

import pandas as pd
import pytest
from PIL import Image

from ml.skin_image.data import load_rgb_image, resolve_image_path
from ml.skin_image.splits import patient_grouped_split


def test_patient_grouped_split_has_no_overlap_and_is_deterministic() -> None:
    frame = pd.DataFrame(
        {
            "patient_id": [f"p{i}" for i in range(30) for _ in range(2)],
            "label": ["A", "B"] * 30,
        }
    )
    first = patient_grouped_split(frame, random_state=17)
    second = patient_grouped_split(frame, random_state=17)
    assert first == second

    partitions = [set(first.train), set(first.validation), set(first.test)]
    assert not (partitions[0] & partitions[1])
    assert not (partitions[0] & partitions[2])
    assert not (partitions[1] & partitions[2])

    groups = [set(frame.iloc[list(indices)]["patient_id"]) for indices in (
        first.train, first.validation, first.test
    )]
    assert not (groups[0] & groups[1])
    assert not (groups[0] & groups[2])
    assert not (groups[1] & groups[2])


def test_patient_grouped_split_rejects_missing_patient_ids() -> None:
    frame = pd.DataFrame({"patient_id": ["p1", "", "p2"], "label": ["A", "A", "B"]})
    with pytest.raises(ValueError, match="nonblank"):
        patient_grouped_split(frame)


def test_patient_grouped_split_rejects_too_few_groups() -> None:
    frame = pd.DataFrame({"patient_id": ["p1", "p1", "p2"], "label": ["A", "B", "A"]})
    with pytest.raises(ValueError, match="At least three"):
        patient_grouped_split(frame)


def test_patient_grouped_split_validates_fractions() -> None:
    frame = pd.DataFrame({"patient_id": ["p1", "p2", "p3"], "label": ["A", "A", "B"]})
    with pytest.raises(ValueError, match="sum to 1"):
        patient_grouped_split(frame, train_fraction=0.6, validation_fraction=0.2, test_fraction=0.3)


def test_load_rgb_image_preserves_canvas_and_rgb(tmp_path) -> None:
    source = tmp_path / "portrait.png"
    Image.new("RGB", (100, 200), color=(200, 10, 10)).save(source)
    result = load_rgb_image(source, image_size=128)
    assert result.mode == "RGB"
    assert result.size == (128, 128)


def test_load_rgb_image_rejects_tiny_image(tmp_path) -> None:
    source = tmp_path / "tiny.png"
    Image.new("RGB", (10, 10)).save(source)
    with pytest.raises(ValueError, match="too small"):
        load_rgb_image(source)


def test_resolve_image_path_blocks_path_traversal(tmp_path) -> None:
    root = tmp_path / "images"
    root.mkdir()
    with pytest.raises(ValueError, match="escapes"):
        resolve_image_path(root, "../../outside.png")


def test_resolve_image_path_accepts_relative_path(tmp_path) -> None:
    root = tmp_path / "images"
    root.mkdir()
    path = root / "one.png"
    path.touch()
    assert resolve_image_path(root, "one.png") == path.resolve()


def test_patient_grouped_split_requires_each_class_in_three_patients() -> None:
    frame = pd.DataFrame(
        {
            "patient_id": ["p1", "p2", "p3", "p4", "p5"],
            "label": ["common", "common", "common", "rare", "rare"],
        }
    )
    with pytest.raises(ValueError, match="three distinct patients"):
        patient_grouped_split(frame)


def test_patient_grouped_split_preserves_every_class_in_each_partition() -> None:
    rows = []
    for index in range(45):
        rows.append(
            {
                "patient_id": f"patient-{index}",
                "label": "class_a" if index % 3 else "class_b",
            }
        )
    frame = pd.DataFrame(rows, index=[100 + index * 3 for index in range(len(rows))])
    result = patient_grouped_split(frame, random_state=31, search_attempts=40)

    partitions = [result.train, result.validation, result.test]
    all_labels = set(frame["label"])
    all_patient_groups = []
    for indices in partitions:
        part = frame.loc[list(indices)]
        assert set(part["label"]) == all_labels
        all_patient_groups.append(set(part["patient_id"]))

    assert not (all_patient_groups[0] & all_patient_groups[1])
    assert not (all_patient_groups[0] & all_patient_groups[2])
    assert not (all_patient_groups[1] & all_patient_groups[2])


def test_patient_grouped_split_rejects_missing_label_column() -> None:
    frame = pd.DataFrame({"patient_id": ["p1", "p2", "p3"]})
    with pytest.raises(ValueError, match="split columns"):
        patient_grouped_split(frame)
