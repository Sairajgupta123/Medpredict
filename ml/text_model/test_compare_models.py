"""Tests for text-model comparison input validation."""

import pytest

from ml.text_model.compare_models import compare_text_models


def test_comparison_rejects_invalid_test_fraction(tmp_path) -> None:
    with pytest.raises(ValueError, match="test_size"):
        compare_text_models(
            tmp_path / "missing.csv",
            tmp_path / "out",
            test_size=0.05,
        )
