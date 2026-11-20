"""Tests for heuristic image-quality screening."""

from PIL import Image

from ml.skin_image.quality import ImageQualityPolicy, inspect_image_quality


def test_quality_flags_low_resolution_image() -> None:
    result = inspect_image_quality(Image.new("RGB", (32, 32), color="gray"))
    assert result["accepted_by_quality_checks"] is False
    assert "resolution_too_low" in result["flags"]


def test_quality_flags_very_dark_image() -> None:
    result = inspect_image_quality(Image.new("RGB", (256, 256), color="black"))
    assert "image_too_dark" in result["flags"]


def test_quality_policy_is_configurable() -> None:
    policy = ImageQualityPolicy(
        min_width=32,
        min_height=32,
        min_mean_luminance=0,
        max_mean_luminance=255,
        max_clipped_pixel_fraction=1,
        min_laplacian_variance=0,
    )
    result = inspect_image_quality(
        Image.new("RGB", (64, 64), color=(100, 110, 120)),
        policy=policy,
    )
    assert result["accepted_by_quality_checks"] is True


def test_quality_reports_decode_failure_without_exposing_path(tmp_path) -> None:
    result = inspect_image_quality(tmp_path / "missing-image.jpg")
    assert result["accepted_by_quality_checks"] is False
    assert result["flags"] == ["image_decode_failed"]
    assert "missing-image.jpg" not in str(result)


def test_quality_policy_rejects_invalid_thresholds() -> None:
    import pytest

    with pytest.raises(ValueError, match="Luminance thresholds"):
        ImageQualityPolicy(min_mean_luminance=200, max_mean_luminance=100)
    with pytest.raises(ValueError, match="positive"):
        ImageQualityPolicy(min_width=0)

def test_quality_policy_rejects_non_finite_thresholds() -> None:
    import pytest

    with pytest.raises(ValueError, match="finite"):
        ImageQualityPolicy(min_mean_luminance=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        ImageQualityPolicy(max_clipped_pixel_fraction=float("inf"))
    with pytest.raises(ValueError, match="finite"):
        ImageQualityPolicy(min_laplacian_variance=float("nan"))


def test_quality_policy_requires_integer_dimensions() -> None:
    import pytest

    with pytest.raises(ValueError, match="positive integers"):
        ImageQualityPolicy(min_width=128.5)
    with pytest.raises(ValueError, match="positive integers"):
        ImageQualityPolicy(min_height=True)
