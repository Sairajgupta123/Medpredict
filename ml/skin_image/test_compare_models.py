"""Tests for the architecture comparison protocol without model training."""

import pytest

from ml.skin_image.compare_models import compare_architectures


def test_comparison_rejects_empty_and_duplicate_candidates(tmp_path) -> None:
    with pytest.raises(ValueError, match="At least one"):
        compare_architectures(
            tmp_path / "manifest.csv",
            tmp_path,
            tmp_path / "out",
            candidates=(),
        )
    with pytest.raises(ValueError, match="unique"):
        compare_architectures(
            tmp_path / "manifest.csv",
            tmp_path,
            tmp_path / "out",
            candidates=(("mobilenet_v3", "large"), ("mobilenet_v3", "large")),
        )


def test_comparison_cli_requires_and_forwards_dataset_approval(monkeypatch, tmp_path) -> None:
    import sys

    import ml.skin_image.compare_models as compare_module

    captured = {}

    def fake_compare(manifest, image_root, output_dir, **kwargs):
        captured.update(kwargs)
        return {
            "status": "research_comparison_only",
            "ranking_metric": "best_validation_macro_f1",
            "ranking": [{"architecture": "mobilenet_v3", "variant": "large"}],
        }

    monkeypatch.setattr(compare_module, "compare_architectures", fake_compare)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "skin-compare",
            "--manifest", str(tmp_path / "manifest.csv"),
            "--image-root", str(tmp_path / "images"),
            "--output-dir", str(tmp_path / "out"),
            "--dataset-registry", str(tmp_path / "registry.json"),
            "--dataset-id", "approved-skin-set-v1",
        ],
    )

    compare_module.main()

    assert captured["dataset_registry_path"] == tmp_path / "registry.json"
    assert captured["dataset_id"] == "approved-skin-set-v1"
