"""Safety-gated inference helper for offline skin-image research.

This function is not a clinical diagnostic endpoint. The caller must supply a reviewed model,
class mapping, calibrated temperature and validation-selected abstention threshold.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageOps

from ml.skin_image.quality import ImageQualityPolicy, inspect_image_quality


def predict_skin_image(
    model: Any,
    image: Image.Image,
    *,
    class_names: list[str],
    minimum_confidence: float,
    temperature: float,
    device: str = "cpu",
    image_size: int = 224,
    quality_policy: ImageQualityPolicy | None = None,
) -> dict[str, Any]:
    """Run research inference after image checks; abstain rather than force a class."""
    if (
        len(class_names) < 2
        or any(not isinstance(name, str) or not name.strip() for name in class_names)
        or len(set(class_names)) != len(class_names)
    ):
        raise ValueError("class_names must contain at least two unique labels, all non-empty")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float, np.integer, np.floating))
        or not np.isfinite(temperature)
        or temperature <= 0
    ):
        raise ValueError("temperature must be positive and finite")
    if (
        isinstance(minimum_confidence, bool)
        or not isinstance(minimum_confidence, (int, float, np.integer, np.floating))
        or not np.isfinite(minimum_confidence)
        or not 0 <= minimum_confidence <= 1
    ):
        raise ValueError("minimum_confidence must be a finite number between 0 and 1")
    if isinstance(image_size, bool) or not isinstance(image_size, int) or image_size < 32:
        raise ValueError("image_size must be an integer of at least 32 pixels")

    quality = inspect_image_quality(image, policy=quality_policy)
    if not quality["accepted_by_quality_checks"]:
        return {
            "status": "image_quality_rejected",
            "prediction": None,
            "confidence": None,
            "quality_flags": quality["flags"],
            "message": (
                "The image did not pass basic quality checks. Retake it with good lighting "
                "and focus. These checks do not establish diagnostic suitability."
            ),
        }

    try:
        import torch
        from torchvision import transforms
    except ImportError as exc:
        raise RuntimeError(
            "Install the optional skin dependencies from ml/requirements-skin.txt"
        ) from exc

    from ml.skin_image.data import IMAGENET_MEAN, IMAGENET_STD
    from ml.skin_image.selective import apply_abstention

    oriented = ImageOps.exif_transpose(image).convert("RGB")
    canvas = ImageOps.pad(
        oriented,
        (image_size, image_size),
        method=Image.Resampling.BILINEAR,
        color=(128, 128, 128),
        centering=(0.5, 0.5),
    )
    transform = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )
    tensor = transform(canvas).unsqueeze(0).to(device)

    model = model.to(device)
    model.eval()
    with torch.inference_mode():
        logits = model(tensor)
        if logits.ndim != 2 or logits.shape != (1, len(class_names)):
            raise ValueError("Model output shape does not match the supplied class mapping")
        probabilities = torch.softmax(logits / temperature, dim=1)
        probability_values = probabilities.detach().cpu().numpy()

    decision = apply_abstention(
        probability_values,
        minimum_confidence=minimum_confidence,
    )
    prediction = decision["predictions"][0]
    confidence = float(decision["confidence"][0])
    if prediction is None:
        return {
            "status": "uncertain_abstained",
            "prediction": None,
            "confidence_score": confidence,
            "confidence_semantics": (
                "Maximum model score after temperature scaling; not a disease probability "
                "or medical certainty."
            ),
            "message": (
                "The model is not sufficiently confident to return a research class. "
                "Please seek assessment from a qualified healthcare professional."
            ),
            "quality_flags": [],
        }

    return {
        "status": "research_prediction",
        "prediction": class_names[prediction],
        "confidence_score": confidence,
        "confidence_semantics": (
            "Maximum model score after temperature scaling; not a disease probability "
            "or medical certainty."
        ),
        "message": (
            "Research output for the model's documented dataset classes only. "
            "This is not a diagnosis and must not replace clinician assessment."
        ),
        "quality_flags": [],
    }
