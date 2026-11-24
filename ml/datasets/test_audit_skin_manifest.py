"""Tests for privacy-conscious skin-image manifest audit."""

import json

import pandas as pd
from PIL import Image

from ml.datasets.audit_skin_manifest import audit_skin_manifest


def test_audit_checks_images_groups_and_duplicate_content(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    Image.new("RGB", (16, 16), color="red").save(image_root / "one.jpg")
    Image.new("RGB", (16, 16), color="red").save(image_root / "duplicate.jpg")
    Image.new("RGB", (0 + 16, 16), color="blue").save(image_root / "two.png")

    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_id": ["i1", "i2", "i3"],
            "image_path": ["one.jpg", "duplicate.jpg", "two.png"],
            "label": ["A", "A", "B"],
            "patient_id": ["p1", "p1", "p2"],
            "lesion_id": ["l1", "l1", "l2"],
        }
    ).to_csv(manifest, index=False)

    report = audit_skin_manifest(manifest, image_root)
    assert report["row_count"] == 3
    assert report["patient_id"]["unique_groups"] == 2
    assert report["lesion_id"]["unique_groups"] == 2
    assert report["content_duplicates"]["duplicate_content_groups"] == 1
    assert report["file_integrity"]["missing_files"] == 0
    assert report["file_integrity"]["decode_failures"] == 0
    assert report["training_readiness"]["ready_for_reviewer_signoff"] is False
    assert "duplicate_image_content_may_cause_data_leakage" in report[
        "training_readiness"
    ]["blocking_reasons"]
    rendered = json.dumps(report)
    assert "p1" not in rendered
    assert "one.jpg" not in rendered


def test_audit_rejects_path_traversal_and_reports_missing_file(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_id": ["i1", "i2"],
            "image_path": ["../../outside.jpg", "missing.jpg"],
            "label": ["A", "B"],
        }
    ).to_csv(manifest, index=False)

    report = audit_skin_manifest(manifest, image_root)
    assert report["file_integrity"]["unsafe_paths_rejected"] == 1
    assert report["file_integrity"]["missing_files"] == 1


def test_audit_requires_manifest_columns(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    manifest = tmp_path / "bad.csv"
    pd.DataFrame({"path": ["a.jpg"], "target": ["A"]}).to_csv(
        manifest, index=False
    )

    import pytest

    with pytest.raises(ValueError, match="missing required columns"):
        audit_skin_manifest(manifest, image_root)


def test_metadata_only_skips_content_duplicate_check(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_id": ["i1"],
            "image_path": ["not-downloaded.jpg"],
            "label": ["A"],
        }
    ).to_csv(manifest, index=False)

    report = audit_skin_manifest(manifest, image_root, inspect_images=False)
    assert report["file_integrity"]["inspection_performed"] is False
    assert report["content_duplicates"]["duplicate_content_groups"] == 0


def test_audit_marks_dataset_ready_only_after_technical_gates(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    rows = []
    for label in ("A", "B"):
        for patient_index in range(3):
            filename = f"{label}_{patient_index}.png"
            Image.new(
                "RGB",
                (256, 256),
                color=(patient_index * 20 + (0 if label == "A" else 100), 80, 120),
            ).save(image_root / filename)
            rows.append(
                {
                    "image_id": f"image-{label}-{patient_index}",
                    "image_path": filename,
                    "label": label,
                    "patient_id": f"patient-{label}-{patient_index}",
                }
            )

    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(rows).to_csv(manifest, index=False)
    report = audit_skin_manifest(manifest, image_root)

    assert report["training_readiness"]["ready_for_reviewer_signoff"] is True
    assert report["training_readiness"]["automatic_training_approval"] is False
    assert report["training_readiness"]["distinct_patients_per_class"] == {
        "A": 3,
        "B": 3,
    }
    rendered = json.dumps(report)
    assert "patient-A-0" not in rendered
    assert "A_0.png" not in rendered


def test_audit_blocks_training_readiness_without_patient_groups(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    Image.new("RGB", (256, 256), color="purple").save(image_root / "one.png")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_id": ["i1"],
            "image_path": ["one.png"],
            "label": ["A"],
        }
    ).to_csv(manifest, index=False)

    report = audit_skin_manifest(manifest, image_root)
    assert report["training_readiness"]["ready_for_reviewer_signoff"] is False
    assert "patient_id_column_missing" in report["training_readiness"]["blocking_reasons"]



def test_audit_blocks_empty_manifest_and_single_class_dataset(tmp_path) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()

    empty_manifest = tmp_path / "empty.csv"
    pd.DataFrame(columns=["image_id", "image_path", "label", "patient_id"]).to_csv(
        empty_manifest, index=False
    )
    empty_report = audit_skin_manifest(empty_manifest, image_root)
    assert "manifest_has_no_rows" in empty_report["training_readiness"]["blocking_reasons"]
    assert "at_least_two_classes_required" in empty_report["training_readiness"]["blocking_reasons"]

    Image.new("RGB", (32, 32), color="orange").save(image_root / "only.png")
    single_class_manifest = tmp_path / "single.csv"
    pd.DataFrame(
        {
            "image_id": ["i1", "i2", "i3"],
            "image_path": ["only.png", "only.png", "only.png"],
            "label": ["A", "A", "A"],
            "patient_id": ["p1", "p2", "p3"],
        }
    ).to_csv(single_class_manifest, index=False)
    single_report = audit_skin_manifest(single_class_manifest, image_root)
    assert "at_least_two_classes_required" in single_report["training_readiness"]["blocking_reasons"]


def test_audit_hashes_images_without_reading_entire_file_into_memory(tmp_path, monkeypatch) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    Image.new("RGB", (16, 16), color="teal").save(image_root / "one.png")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "image_id": ["i1"],
            "image_path": ["one.png"],
            "label": ["A"],
            "patient_id": ["p1"],
        }
    ).to_csv(manifest, index=False)

    def reject_read_bytes(_self):
        raise AssertionError("Image hashing must use bounded-memory streaming reads")

    monkeypatch.setattr("pathlib.Path.read_bytes", reject_read_bytes)
    report = audit_skin_manifest(manifest, image_root)
    assert report["file_integrity"]["decode_failures"] == 0
    assert report["content_duplicates"]["duplicate_content_groups"] == 0
