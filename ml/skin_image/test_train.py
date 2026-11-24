"""Tests for skin training preflight validation."""

import pandas as pd
import pytest

from ml.skin_image.train import train_skin_model


def test_training_artifact_hash_uses_streaming_reads(tmp_path, monkeypatch) -> None:
    import hashlib
    from pathlib import Path

    from ml.skin_image.train import _sha256_file

    artifact = tmp_path / "large-manifest.csv"
    payload = b"image_path,label,patient_id\\n" + (b"images/a.jpg,class_a,p1\\n" * 1000)
    artifact.write_bytes(payload)

    def reject_read_bytes(_self):
        raise AssertionError("Training artifact hashing must use bounded-memory reads")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
    assert _sha256_file(artifact) == hashlib.sha256(payload).hexdigest()


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



def test_training_cli_forwards_validation_coverage(monkeypatch, tmp_path) -> None:
    import sys

    import ml.skin_image.train as train_module

    captured = {}

    def fake_train_skin_model(manifest, image_root, output_dir, **kwargs):
        captured.update(kwargs)
        return {
            "status": "research_experiment_only",
            "best_epoch": 1,
            "test_metrics": {"macro_f1": 0.5},
        }

    monkeypatch.setattr(train_module, "train_skin_model", fake_train_skin_model)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "skin-train",
            "--manifest",
            str(tmp_path / "manifest.csv"),
            "--image-root",
            str(tmp_path / "images"),
            "--output-dir",
            str(tmp_path / "output"),
            "--target-validation-coverage",
            "0.82",
        ],
    )

    train_module.main()

    assert captured["target_validation_coverage"] == pytest.approx(0.82)

def test_skin_artifact_guard_rejects_existing_checkpoint(tmp_path) -> None:
    from ml.skin_image.train import ensure_skin_artifacts_do_not_exist

    (tmp_path / "skin_mobilenet_v3_large_best.pt").write_bytes(b"prior checkpoint")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        ensure_skin_artifacts_do_not_exist(
            tmp_path,
            [
                "experiment_config.json",
                "skin_mobilenet_v3_large_best.pt",
                "model_metadata.json",
                "experiment_report.json",
            ],
        )


def test_skin_artifact_guard_allows_new_output_directory(tmp_path) -> None:
    from ml.skin_image.train import ensure_skin_artifacts_do_not_exist

    ensure_skin_artifacts_do_not_exist(
        tmp_path / "new-run",
        ["experiment_config.json", "model_metadata.json"],
    )


def test_training_refuses_existing_output_before_reading_manifest(tmp_path) -> None:
    from ml.skin_image.train import train_skin_model

    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_path": ["one.jpg"],
            "label": ["class_a"],
            "patient_id": ["patient-1"],
        }
    ).to_csv(manifest, index=False)
    image_root = tmp_path / "images"
    image_root.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    report = output / "experiment_report.json"
    report.write_text('{"keep": true}', encoding="utf-8")

    with pytest.raises(FileExistsError, match="experiment_report.json"):
        train_skin_model(manifest, image_root, output)

    assert report.read_text(encoding="utf-8") == '{"keep": true}'



@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"epochs": True}, "epochs must be an integer"),
        ({"batch_size": 1.5}, "batch_size must be an integer"),
        ({"seed": False}, "seed must be an integer"),
        ({"num_workers": -1}, "num_workers cannot be negative"),
        ({"learning_rate": float("nan")}, "positive finite"),
        ({"learning_rate": float("inf")}, "positive finite"),
        ({"target_validation_coverage": True}, "finite number"),
        ({"target_validation_coverage": float("nan")}, "finite number"),
        ({"architecture": "unknown"}, "architecture must be"),
        ({"architecture": "resnet50", "variant": "large"}, "variant is inconsistent"),
    ],
)
def test_training_rejects_invalid_configuration_before_torch_import(
    tmp_path, kwargs, message
) -> None:
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

    with pytest.raises(ValueError, match=message):
        train_skin_model(
            manifest,
            image_root,
            tmp_path / "output",
            **kwargs,
        )
