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
