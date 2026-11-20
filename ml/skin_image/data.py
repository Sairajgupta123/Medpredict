"""PyTorch skin-image dataset and conservative preprocessing.

Importing this module does not require PyTorch. Install ml/requirements-skin.txt to use
SkinImageDataset and build_image_transform.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, ImageOps


REQUIRED_COLUMNS = {"image_path", "label"}
DEFAULT_IMAGE_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def resolve_image_path(image_root: Path, relative_path: str) -> Path:
    """Resolve a manifest path while preventing traversal outside the image root."""
    root = image_root.resolve()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Manifest image path escapes the configured image root")
    return candidate


def prepare_rgb_image(image: Image.Image, image_size: int = DEFAULT_IMAGE_SIZE) -> Image.Image:
    """Apply EXIF orientation, RGB conversion and the shared aspect-preserving canvas."""
    if isinstance(image_size, bool) or not isinstance(image_size, int) or image_size < 32:
        raise ValueError("image_size must be an integer of at least 32 pixels")
    oriented = ImageOps.exif_transpose(image).convert("RGB")
    if oriented.width < 32 or oriented.height < 32:
        raise ValueError("Image dimensions are too small for analysis")
    return ImageOps.pad(
        oriented,
        (image_size, image_size),
        method=Image.Resampling.BILINEAR,
        color=(128, 128, 128),
        centering=(0.5, 0.5),
    )


def load_rgb_image(path: Path, image_size: int = DEFAULT_IMAGE_SIZE) -> Image.Image:
    """Decode an image and apply the shared RGB preprocessing pipeline."""
    if isinstance(image_size, bool) or not isinstance(image_size, int) or image_size < 32:
        raise ValueError("image_size must be an integer of at least 32 pixels")
    if not path.is_file():
        raise FileNotFoundError("Image file is missing")
    try:
        with Image.open(path) as source:
            image = source.copy()
            image.load()
    except (OSError, ValueError) as exc:
        raise ValueError("Image could not be decoded") from exc
    return prepare_rgb_image(image, image_size)


def build_image_transform(*, training: bool, image_size: int = DEFAULT_IMAGE_SIZE):
    """Create a conservative transform; training augmentation avoids color jitter."""
    try:
        from torchvision import transforms
    except ImportError as exc:
        raise RuntimeError(
            "Install the optional skin dependencies from ml/requirements-skin.txt"
        ) from exc

    operations: list[Any] = []
    if training:
        operations.extend(
            [
                transforms.RandomHorizontalFlip(p=0.5),
                transforms.RandomRotation(degrees=8, fill=(128, 128, 128)),
            ]
        )
    operations.extend(
        [
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )
    return transforms.Compose(operations)


class SkinImageDataset:
    """Small manifest-backed torch Dataset; does not expose patient IDs to the model."""

    def __new__(
        cls,
        manifest: pd.DataFrame,
        image_root: Path,
        *,
        label_to_index: dict[str, int] | None = None,
        training: bool = False,
        image_size: int = DEFAULT_IMAGE_SIZE,
    ):
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "Install the optional skin dependencies from ml/requirements-skin.txt"
            ) from exc

        class _Dataset(torch.utils.data.Dataset):
            def __init__(self):
                missing = REQUIRED_COLUMNS - set(manifest.columns)
                if missing:
                    raise ValueError(
                        f"Manifest is missing required columns: {sorted(missing)}"
                    )
                self.frame = manifest.reset_index(drop=True).copy()
                self.image_root = image_root
                labels = sorted(
                    self.frame["label"].fillna("").astype(str).str.strip().unique()
                )
                if not labels or any(not label for label in labels):
                    raise ValueError("Manifest contains blank or missing labels")
                self.label_to_index = label_to_index or {
                    label: index for index, label in enumerate(labels)
                }
                unknown = set(labels) - set(self.label_to_index)
                if unknown:
                    raise ValueError("Manifest contains labels absent from label mapping")
                if len(set(self.label_to_index.values())) != len(self.label_to_index):
                    raise ValueError("Label mapping indices must be unique")
                self.transform = build_image_transform(
                    training=training, image_size=image_size
                )
                self.image_size = image_size

            def __len__(self) -> int:
                return len(self.frame)

            def __getitem__(self, index: int):
                row = self.frame.iloc[index]
                path = resolve_image_path(
                    self.image_root, str(row["image_path"])
                )
                image = load_rgb_image(path, self.image_size)
                tensor = self.transform(image)
                target = self.label_to_index[str(row["label"]).strip()]
                return tensor, target

        return _Dataset()
