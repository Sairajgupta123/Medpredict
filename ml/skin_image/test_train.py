"""Tests for skin training preflight validation."""

import pandas as pd
import pytest

from ml.skin_image.train import train_skin_model


def test_training_rejects_missing_patient_column(tmp_path) -> None:
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {"image_path": ["a.png"], "label": ["class_a"]}
    ).to_csv(manifest, index=False)
    image_root = tmp_path / "images"
    image_root.mkdir()

    # Preflight is performed before importing or initializing torch.
    with pytest.raises(ValueError, match="patient_id"):
        train_skin_model(
            manifest,
            image_root,
            tmp_path / "output",
        )


def test_training_rejects_missing_manifest(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    with pytest.raises(FileNotFoundError):
        train_skin_model(
            tmp_path / "missing.csv",
            image_root,
            tmp_path / "output",
        )


def test_training_rejects_invalid_validation_coverage_before_loading_torch(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_path": ["one.jpg"],
            "label": ["class_a"],
            "patient_id": ["patient-1"],
        }
    ).to_csv(manifest, index=False)

    with pytest.raises(ValueError, match="target_validation_coverage"):
        train_skin_model(
            manifest,
            image_root,
            tmp_path / "output",
            target_validation_coverage=0,
        )


def test_training_blocks_dataset_with_missing_image_files(tmp_path) -> None:
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_id": [f"image-{i}" for i in range(6)],
            "image_path": [f"missing-{i}.jpg" for i in range(6)],
            "label": ["class_a"] * 3 + ["class_b"] * 3,
            "patient_id": [f"patient-{i}" for i in range(6)],
        }
    ).to_csv(manifest, index=False)
    image_root = tmp_path / "images"
    image_root.mkdir()

    # A technically incomplete dataset must be rejected before torch/model initialization.
    with pytest.raises(ValueError, match="image_files_missing_or_unsafe"):
        train_skin_model(
            manifest,
            image_root,
            tmp_path / "output",
        )
