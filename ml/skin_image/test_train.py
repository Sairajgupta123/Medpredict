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
