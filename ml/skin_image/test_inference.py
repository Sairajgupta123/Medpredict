"""Tests for safety-gated skin image inference."""

import numpy as np
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

@pytest.mark.parametrize(
    ("parameter", "value", "message"),
    [
        ("temperature", True, "positive and finite"),
        ("temperature", float("nan"), "positive and finite"),
        ("minimum_confidence", True, "finite number"),
        ("minimum_confidence", float("inf"), "finite number"),
        ("image_size", 224.5, "integer"),
        ("image_size", True, "integer"),
    ],
)
def test_inference_rejects_invalid_numeric_parameters(
    parameter: str, value: object, message: str
) -> None:
    image = Image.new("RGB", (256, 256), color=(100, 110, 120))
    kwargs = {
        "class_names": ["class_a", "class_b"],
        "minimum_confidence": 0.7,
        "temperature": 1.0,
    }
    kwargs[parameter] = value
    with pytest.raises(ValueError, match=message):
        predict_skin_image(NeverCalledModel(), image, **kwargs)

def _valid_checkpoint_and_metadata():
    import hashlib
    import json

    config = {
        "architecture": "mobilenet_v3",
        "variant": "large",
        "image_size": 224,
    }
    digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    checkpoint = {
        "model_state_dict": {"classifier.weight": np.ones((2, 2), dtype=np.float32)},
        "class_names": ["class_a", "class_b"],
        "class_to_index": {"class_a": 0, "class_b": 1},
        "architecture": "mobilenet_v3",
        "model_variant": "large",
        "image_size": 224,
        "normalization": "ImageNet mean/std",
        "calibration_temperature": 1.2,
        "abstention_threshold": 0.65,
        "threshold_selection_partition": "validation_only",
        "experiment_config": config,
        "experiment_config_sha256": digest,
        "manifest_sha256": "manifest-digest",
    }
    metadata = {
        "architecture": "mobilenet_v3",
        "variant": "large",
        "class_names": ["class_a", "class_b"],
        "class_to_index": {"class_a": 0, "class_b": 1},
        "image_size": 224,
        "normalization": {
            "name": "ImageNet",
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
        },
        "manifest_sha256": "manifest-digest",
        "experiment_config_sha256": digest,
        "calibration_temperature": 1.2,
        "abstention_threshold": 0.65,
        "threshold_selection_partition": "validation_only",
        "clinical_validation": False,
        "intended_use": "offline_research_only",
    }
    return checkpoint, metadata


def test_checkpoint_metadata_validation_returns_inference_settings() -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    result = validate_skin_checkpoint(checkpoint, metadata)
    assert result == {
        "class_names": ["class_a", "class_b"],
        "architecture": "mobilenet_v3",
        "variant": "large",
        "image_size": 224,
        "temperature": 1.2,
        "minimum_confidence": 0.65,
    }


def test_checkpoint_validation_rejects_wrong_class_index_mapping() -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    checkpoint["class_to_index"] = {"class_a": 1, "class_b": 0}
    with pytest.raises(ValueError, match="class mapping"):
        validate_skin_checkpoint(checkpoint, metadata)


def test_checkpoint_validation_rejects_metadata_calibration_mismatch() -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    metadata["abstention_threshold"] = 0.8
    with pytest.raises(ValueError, match="abstention_threshold"):
        validate_skin_checkpoint(checkpoint, metadata)


def test_checkpoint_validation_rejects_modified_experiment_config() -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    checkpoint["experiment_config"]["image_size"] = 256
    with pytest.raises(ValueError, match="digest"):
        validate_skin_checkpoint(checkpoint, metadata)


def test_checkpoint_validation_requires_validation_selected_threshold() -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    checkpoint["threshold_selection_partition"] = "test"
    with pytest.raises(ValueError, match="validation data only"):
        validate_skin_checkpoint(checkpoint, metadata)


@pytest.mark.parametrize(
    ("state_dict", "message"),
    [
        ({}, "non-empty mapping"),
        ({"": np.ones((1,), dtype=np.float32)}, "non-empty strings"),
        ({"weight": np.asarray(["not-a-weight"])}, "numeric tensor"),
        ({"weight": np.asarray([float("nan")])}, "non-finite values"),
        ({"weight": np.asarray([float("inf")])}, "non-finite values"),
        ({"weight": np.asarray([], dtype=np.float32)}, "non-empty numeric tensor"),
    ],
)
def test_checkpoint_validation_rejects_invalid_model_weights(
    state_dict: dict, message: str
) -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    checkpoint["model_state_dict"] = state_dict
    with pytest.raises(ValueError, match=message):
        validate_skin_checkpoint(checkpoint, metadata)
