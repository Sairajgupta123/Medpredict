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
