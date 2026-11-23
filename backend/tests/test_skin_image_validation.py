"""Tests for safe, bounded skin-image validation and metadata removal."""

from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from app.services.skin_image_validation import (
    MAX_IMAGE_BYTES,
    validate_and_sanitize_skin_image,
)


def _image_bytes(
    image_format: str = "PNG",
    size: tuple[int, int] = (32, 24),
    color: tuple[int, int, int] = (120, 80, 40),
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("image_format", "content_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_accepts_supported_formats_and_returns_decodable_sanitized_image(
    image_format: str, content_type: str
) -> None:
    result = validate_and_sanitize_skin_image(
        _image_bytes(image_format), content_type
    )
    assert result.format == image_format
    assert result.content_type == content_type
    assert (result.width, result.height) == (32, 24)
    assert result.byte_size == len(result.content)
    with Image.open(BytesIO(result.content)) as decoded:
        assert decoded.format == image_format
        assert decoded.size == (32, 24)


def test_rejects_empty_and_oversized_payloads() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        validate_and_sanitize_skin_image(b"", "image/png")
    with pytest.raises(ValueError, match="8 MiB"):
        validate_and_sanitize_skin_image(
            b"x" * (MAX_IMAGE_BYTES + 1), "image/png"
        )


def test_rejects_mismatched_content_type() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_and_sanitize_skin_image(_image_bytes("PNG"), "image/jpeg")


def test_rejects_unsupported_and_non_image_bytes() -> None:
    with pytest.raises(ValueError, match="Only JPEG"):
        validate_and_sanitize_skin_image(_image_bytes("GIF"), "image/png")
    with pytest.raises(ValueError, match="invalid or cannot be decoded"):
        validate_and_sanitize_skin_image(b"not an image", "image/png")


def test_rejects_dimensions_over_limits_before_full_decode() -> None:
    with pytest.raises(ValueError, match="dimensions exceed"):
        validate_and_sanitize_skin_image(
            _image_bytes(size=(6001, 1)), "image/png"
        )


def test_strips_png_text_metadata() -> None:
    buffer = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private_note", "do not retain this metadata")
    Image.new("RGB", (16, 16), (1, 2, 3)).save(
        buffer, format="PNG", pnginfo=metadata
    )
    result = validate_and_sanitize_skin_image(buffer.getvalue(), "image/png")
    with Image.open(BytesIO(result.content)) as sanitized:
        assert "private_note" not in sanitized.info


def test_rejects_animated_webp() -> None:
    first = Image.new("RGB", (8, 8), (0, 0, 0))
    second = Image.new("RGB", (8, 8), (255, 255, 255))
    buffer = BytesIO()
    first.save(
        buffer,
        format="WEBP",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    with pytest.raises(ValueError, match="Animated"):
        validate_and_sanitize_skin_image(buffer.getvalue(), "image/webp")


def test_quality_assessment_flags_small_dark_uniform_image() -> None:
    from app.services.skin_image_validation import assess_skin_image_quality

    result = assess_skin_image_quality(
        _image_bytes(size=(64, 64), color=(10, 10, 10))
    )
    assert result.width == 64
    assert result.height == 64
    assert "low_resolution" in result.warnings
    assert "possibly_too_dark" in result.warnings
    assert "low_contrast_or_uniform_image" in result.warnings


def test_quality_assessment_does_not_call_technical_checks_a_diagnosis() -> None:
    from app.services.skin_image_validation import assess_skin_image_quality

    result = assess_skin_image_quality(_image_bytes(size=(512, 512)))
    assert isinstance(result.warnings, tuple)
    assert result.mean_luminance >= 0
    assert result.luminance_spread >= 0


def test_quality_assessment_rejects_invalid_bytes() -> None:
    from app.services.skin_image_validation import assess_skin_image_quality

    with pytest.raises(ValueError, match="invalid or cannot be decoded"):
        assess_skin_image_quality(b"not sanitized image bytes")

def test_strips_jpeg_exif_metadata() -> None:
    buffer = BytesIO()
    exif = Image.Exif()
    exif[0x010E] = "private location note"
    Image.new("RGB", (32, 24), (40, 80, 120)).save(
        buffer, format="JPEG", exif=exif
    )

    result = validate_and_sanitize_skin_image(buffer.getvalue(), "image/jpeg")

    with Image.open(BytesIO(result.content)) as sanitized:
        assert sanitized.format == "JPEG"
        assert sanitized.size == (32, 24)
        assert not sanitized.getexif()
        assert "exif" not in sanitized.info

