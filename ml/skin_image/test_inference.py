"""Tests for safety-gated skin image inference."""

import pytest
from PIL import Image

from ml.skin_image.inference import predict_skin_image


class NeverCalledModel:
    def to(self, device):
        raise AssertionError("Model must not run when quality checks reject the image")


def test_inference_rejects_low_resolution_before_model_execution() -> None:
    result = predict_skin_image(
        NeverCalledModel(),
        Image.new("RGB", (32, 32), color="gray"),
        class_names=["class_a", "class_b"],
        minimum_confidence=0.7,
        temperature=1.0,
    )
    assert result["status"] == "image_quality_rejected"
    assert result["prediction"] is None
    assert "resolution_too_low" in result["quality_flags"]


def test_inference_validates_class_mapping_and_thresholds() -> None:
    image = Image.new("RGB", (256, 256), color=(100, 110, 120))
    with pytest.raises(ValueError, match="unique labels"):
        predict_skin_image(
            NeverCalledModel(),
            image,
            class_names=["same", "same"],
            minimum_confidence=0.7,
            temperature=1.0,
        )

    with pytest.raises(ValueError, match="non-empty"):
        predict_skin_image(
            NeverCalledModel(),
            image,
            class_names=["class_a", " "],
            minimum_confidence=0.7,
            temperature=1.0,
        )
    with pytest.raises(ValueError, match="positive and finite"):
        predict_skin_image(
            NeverCalledModel(),
            image,
            class_names=["class_a", "class_b"],
            minimum_confidence=0.7,
            temperature=0,
        )
