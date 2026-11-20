"""Tests for training-only class weight calculation."""

import pytest

from ml.skin_image.class_weights import calculate_class_weights


def test_balanced_class_weights_are_equal() -> None:
    result = calculate_class_weights([0, 0, 1, 1], class_count=2)
    assert result["class_counts"] == [2, 2]
    assert result["class_weights"] == pytest.approx([1.0, 1.0])
    assert result["source_partition"] == "training_only"


def test_minority_class_receives_higher_weight() -> None:
    result = calculate_class_weights([0, 0, 0, 1], class_count=2)
    assert result["class_weights"][1] > result["class_weights"][0]


def test_class_weights_reject_missing_classes_and_invalid_labels() -> None:
    with pytest.raises(ValueError, match="missing class"):
        calculate_class_weights([0, 0, 0], class_count=2)
    with pytest.raises(ValueError, match="integer"):
        calculate_class_weights([0.5, 1.0], class_count=2)
    with pytest.raises(ValueError, match="outside"):
        calculate_class_weights([0, 2], class_count=2)
