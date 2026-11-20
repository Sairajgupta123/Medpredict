"""Heuristic image-quality screening for research ingestion.

Thresholds are configurable and intentionally not presented as clinically validated. Quality
screening cannot establish that an image depicts a supported condition or modality.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class ImageQualityPolicy:
    min_width: int = 128
    min_height: int = 128
    min_mean_luminance: float = 18.0
    max_mean_luminance: float = 238.0
    max_clipped_pixel_fraction: float = 0.55
    min_laplacian_variance: float = 8.0

    def __post_init__(self) -> None:
        if self.min_width < 1 or self.min_height < 1:
            raise ValueError("Minimum image dimensions must be positive")
        if not 0 <= self.min_mean_luminance < self.max_mean_luminance <= 255:
            raise ValueError("Luminance thresholds must satisfy 0 <= min < max <= 255")
        if not 0 <= self.max_clipped_pixel_fraction <= 1:
            raise ValueError("Clipped-pixel fraction must be between 0 and 1")
        if self.min_laplacian_variance < 0:
            raise ValueError("Minimum detail score cannot be negative")


def _laplacian_variance(gray: np.ndarray) -> float:
    """Estimate high-frequency detail using a simple four-neighbour Laplacian."""
    pixels = gray.astype(np.float32)
    if pixels.shape[0] < 3 or pixels.shape[1] < 3:
        return 0.0
    center = pixels[1:-1, 1:-1]
    laplacian = (
        pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
        - 4.0 * center
    )
    return float(np.var(laplacian))


def inspect_image_quality(
    image_or_path: Image.Image | Path,
    *,
    policy: ImageQualityPolicy | None = None,
) -> dict[str, Any]:
    """Return heuristic quality flags; never infer a disease or diagnostic suitability."""
    policy = policy or ImageQualityPolicy()
    close_after = False
    if isinstance(image_or_path, Path):
        try:
            image = Image.open(image_or_path)
            close_after = True
        except (OSError, ValueError) as exc:
            return {
                "accepted_by_quality_checks": False,
                "flags": ["image_decode_failed"],
                "metrics": {},
                "policy": asdict(policy),
            }
    else:
        image = image_or_path

    try:
        oriented = ImageOps.exif_transpose(image).convert("RGB")
        width, height = oriented.size
        gray = np.asarray(oriented.convert("L"), dtype=np.uint8)
        mean_luminance = float(gray.mean())
        clipped_fraction = float(
            np.mean((gray <= 5) | (gray >= 250))
        )
        blur_score = _laplacian_variance(gray)

        flags: list[str] = []
        if width < policy.min_width or height < policy.min_height:
            flags.append("resolution_too_low")
        if mean_luminance < policy.min_mean_luminance:
            flags.append("image_too_dark")
        if mean_luminance > policy.max_mean_luminance:
            flags.append("image_too_bright")
        if clipped_fraction > policy.max_clipped_pixel_fraction:
            flags.append("excessive_clipped_pixels")
        if blur_score < policy.min_laplacian_variance:
            flags.append("possible_blur_or_low_detail")

        return {
            "accepted_by_quality_checks": not flags,
            "flags": flags,
            "metrics": {
                "width": width,
                "height": height,
                "mean_luminance": mean_luminance,
                "clipped_pixel_fraction": clipped_fraction,
                "laplacian_variance": blur_score,
            },
            "policy": asdict(policy),
            "notice": (
                "Passing these heuristic checks does not establish diagnostic suitability, "
                "supported image modality, or absence of out-of-distribution content."
            ),
        }
    finally:
        if close_after:
            image.close()
