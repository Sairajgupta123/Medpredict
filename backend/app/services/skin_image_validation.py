"""Security-first validation and metadata sanitization for skin images.

This module intentionally does not persist files or perform disease inference.
Callers must not expose an upload endpoint until private storage, consent,
retention, deletion, and request-level controls are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_WIDTH = 6_000
MAX_IMAGE_HEIGHT = 6_000
MAX_IMAGE_PIXELS = 20_000_000
SUPPORTED_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


@dataclass(frozen=True)
class ValidatedSkinImage:
    """Validated, re-encoded image bytes with metadata removed."""

    content: bytes
    content_type: str
    format: str
    width: int
    height: int
    byte_size: int


def validate_and_sanitize_skin_image(
    content: bytes, declared_content_type: str
) -> ValidatedSkinImage:
    """Validate actual image bytes and return a metadata-free re-encoding.

    The decoder, not the filename or request header, determines the format.
    Only single-frame JPEG, PNG and WebP images are accepted.
    """
    if not isinstance(content, bytes) or not content:
        raise ValueError("Image content must be a non-empty byte sequence.")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 8 MiB upload limit.")
    if declared_content_type not in {item[0] for item in SUPPORTED_FORMATS.values()}:
        raise ValueError("Unsupported declared image content type.")

    try:
        with Image.open(BytesIO(content)) as probe:
            detected_format = probe.format
            if detected_format not in SUPPORTED_FORMATS:
                raise ValueError("Only JPEG, PNG and WebP images are supported.")
            expected_type, _ = SUPPORTED_FORMATS[detected_format]
            if declared_content_type != expected_type:
                raise ValueError("Declared content type does not match image bytes.")
            if getattr(probe, "n_frames", 1) != 1:
                raise ValueError("Animated or multi-frame images are not supported.")
            width, height = probe.size
            if width < 1 or height < 1:
                raise ValueError("Image dimensions are invalid.")
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                raise ValueError("Image dimensions exceed the 6000 pixel limit.")
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Image exceeds the 20 megapixel processing limit.")
            probe.verify()

        with Image.open(BytesIO(content)) as source:
            source.load()
            oriented = ImageOps.exif_transpose(source)
            if detected_format == "JPEG":
                mode = "RGB"
            elif detected_format == "PNG":
                mode = "RGBA" if "A" in oriented.getbands() else "RGB"
            else:
                mode = "RGBA" if "A" in oriented.getbands() else "RGB"

            width, height = oriented.size
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                raise ValueError("Oriented image dimensions exceed the 6000 pixel limit.")
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Oriented image exceeds the 20 megapixel processing limit.")
            pixels = oriented.convert(mode)
            # Rebuild from raw pixels so EXIF, ICC, textual and other metadata
            # cannot be copied into the sanitized output.
            clean = Image.frombytes(mode, pixels.size, pixels.tobytes())
            output = BytesIO()
            save_options: dict[str, object] = {}
            if detected_format == "JPEG":
                save_options = {"quality": 90, "optimize": True}
            elif detected_format == "PNG":
                save_options = {"optimize": True}
            else:
                save_options = {"quality": 90, "method": 4}
            clean.save(output, format=detected_format, **save_options)
            sanitized = output.getvalue()
            clean.close()
            pixels.close()
            oriented.close()

    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Image bytes are invalid or cannot be decoded.") from exc

    return ValidatedSkinImage(
        content=sanitized,
        content_type=expected_type,
        format=detected_format,
        width=width,
        height=height,
        byte_size=len(sanitized),
    )


@dataclass(frozen=True)
class SkinImageQualityAssessment:
    """Non-clinical technical image checks; never a diagnostic quality score."""

    width: int
    height: int
    mean_luminance: float
    luminance_spread: float
    warnings: tuple[str, ...]


def assess_skin_image_quality(content: bytes) -> SkinImageQualityAssessment:
    """Return conservative capture warnings for an already sanitized image.

    These simple pixel statistics cannot establish clinical suitability,
    detect all blur/focus issues, or determine whether a lesion is visible.
    Warnings are advisory and must not be used to diagnose or reject a patient.
    """
    if not isinstance(content, bytes) or not content:
        raise ValueError("Sanitized image content must be non-empty bytes.")

    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in SUPPORTED_FORMATS:
                raise ValueError("Only sanitized JPEG, PNG and WebP images are supported.")
            image.load()
            grayscale = image.convert("L")
            stats = ImageStat.Stat(grayscale)
            mean_luminance = float(stats.mean[0])
            luminance_spread = float(stats.stddev[0])
            width, height = image.size
            grayscale.close()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Sanitized image bytes are invalid or cannot be decoded.") from exc

    warnings: list[str] = []
    if min(width, height) < 256:
        warnings.append("low_resolution")
    if mean_luminance < 45:
        warnings.append("possibly_too_dark")
    elif mean_luminance > 220:
        warnings.append("possibly_overexposed")
    if luminance_spread < 18:
        warnings.append("low_contrast_or_uniform_image")

    return SkinImageQualityAssessment(
        width=width,
        height=height,
        mean_luminance=round(mean_luminance, 2),
        luminance_spread=round(luminance_spread, 2),
        warnings=tuple(warnings),
    )
