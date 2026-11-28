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


@pytest.mark.parametrize("class_names", [None, "class_a,class_b", ("class_a", "class_b"), 42])
def test_inference_rejects_non_list_class_mapping(class_names) -> None:
    image = Image.new("RGB", (256, 256), color=(100, 110, 120))
    with pytest.raises(ValueError, match="class_names must be a list"):
        predict_skin_image(
            NeverCalledModel(),
            image,
            class_names=class_names,
            minimum_confidence=0.7,
            temperature=1.0,
        )


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

    governance = {
        "dataset_id": "approved-skin-set-v1",
        "source_url": "https://example.org/skin-dataset",
        "version": "1.0",
        "license": "CC-BY-4.0",
        "image_domain": "dermoscopy",
        "approval_status": "research_only_approved",
        "governance_reviews": {
            "license_review": "approved",
            "permitted_use_review": "approved",
            "privacy_review": "approved",
            "label_review": "approved",
            "clinical_reviewer_signoff": "approved",
        },
        "registry_sha256": "b" * 64,
    }
    config = {
        "architecture": "mobilenet_v3",
        "variant": "large",
        "image_size": 224,
        "dataset_governance": governance,
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
        "manifest_sha256": "a" * 64,
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
        "manifest_sha256": "a" * 64,
        "experiment_config_sha256": digest,
        "calibration_temperature": 1.2,
        "abstention_threshold": 0.65,
        "threshold_selection_partition": "validation_only",
        "dataset_governance": dict(governance),
        "clinical_validation": False,
        "intended_use": "offline_research_only",
    }
    return checkpoint, metadata


def test_checkpoint_validation_rejects_unapproved_dataset_provenance() -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    checkpoint["experiment_config"]["dataset_governance"]["approval_status"] = "not_approved"
    import hashlib
    import json
    checkpoint["experiment_config_sha256"] = hashlib.sha256(
        json.dumps(checkpoint["experiment_config"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="governance provenance"):
        validate_skin_checkpoint(checkpoint, metadata)


def test_checkpoint_validation_rejects_metadata_governance_mismatch() -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    import hashlib
    import json

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    metadata["dataset_governance"]["dataset_id"] = "different-dataset"
    checkpoint["experiment_config_sha256"] = hashlib.sha256(
        json.dumps(checkpoint["experiment_config"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="dataset_governance"):
        validate_skin_checkpoint(checkpoint, metadata)


@pytest.mark.parametrize("metadata", [[], "metadata", 42])
def test_checkpoint_validation_rejects_non_object_metadata(metadata) -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, _ = _valid_checkpoint_and_metadata()
    with pytest.raises(ValueError, match="Model metadata must be a JSON object"):
        validate_skin_checkpoint(checkpoint, metadata)


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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing required fields"),
        ("malformed", "lowercase SHA-256 hex digest"),
    ],
)
def test_checkpoint_validation_requires_valid_manifest_digest(mutation, message) -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    if mutation == "missing":
        checkpoint.pop("manifest_sha256")
    else:
        checkpoint["manifest_sha256"] = "not-a-sha256"
    with pytest.raises(ValueError, match=message):
        validate_skin_checkpoint(checkpoint, metadata)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("architecture", ["mobilenet_v3"], "architecture is unsupported"),
        ("architecture", {"name": "mobilenet_v3"}, "architecture is unsupported"),
        ("model_variant", ["large"], "architecture and variant are inconsistent"),
        ("model_variant", {"name": "large"}, "architecture and variant are inconsistent"),
    ],
)
def test_checkpoint_validation_rejects_non_string_architecture_fields(
    field, value, message
) -> None:
    from ml.skin_image.inference import validate_skin_checkpoint

    checkpoint, metadata = _valid_checkpoint_and_metadata()
    checkpoint[field] = value
    with pytest.raises(ValueError, match=message):
        validate_skin_checkpoint(checkpoint, metadata)


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



def test_skin_loader_rejects_modified_checkpoint_before_torch_load(tmp_path):
    import hashlib
    import json

    from ml.skin_image.inference import load_skin_research_model

    checkpoint = tmp_path / "skin_model.pt"
    metadata_path = tmp_path / "model_metadata.json"
    manifest_path = tmp_path / "artifact_manifest.json"
    checkpoint.write_bytes(b"original")
    metadata = {"intended_use": "offline_research_only", "clinical_validation": False}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    manifest = {
        "purpose": "offline_research_only",
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": hashlib.sha256(b"not-original").hexdigest(),
        "metadata_file": metadata_path.name,
        "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="checkpoint digest mismatch"):
        load_skin_research_model(str(checkpoint.resolve()))



def test_skin_loader_wraps_unsafe_pickle_error(tmp_path, monkeypatch):
    import hashlib
    import json
    import pickle
    import sys
    import types

    from ml.skin_image.inference import load_skin_research_model

    checkpoint = tmp_path / "model.pt"
    metadata_path = tmp_path / "model_metadata.json"
    manifest_path = tmp_path / "artifact_manifest.json"
    checkpoint.write_bytes(b"checkpoint")
    metadata = {"intended_use": "offline_research_only", "clinical_validation": False}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    manifest = {
        "purpose": "offline_research_only",
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "metadata_file": metadata_path.name,
        "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fake_torch = types.ModuleType("torch")
    def unsafe_load(*args, **kwargs):
        raise pickle.UnpicklingError("unsupported global in checkpoint")
    fake_torch.load = unsafe_load
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    with pytest.raises(ValueError, match="could not be loaded safely"):
        load_skin_research_model(str(checkpoint.resolve()))




def test_skin_loader_normalizes_architecture_weight_mismatch(tmp_path, monkeypatch):
    import hashlib
    import json
    import sys
    import types

    import ml.skin_image.model as model_module
    from ml.skin_image.inference import load_skin_research_model

    checkpoint_data, metadata = _valid_checkpoint_and_metadata()
    checkpoint_path = tmp_path / "skin_model.pt"
    metadata_path = tmp_path / "model_metadata.json"
    manifest_path = tmp_path / "artifact_manifest.json"
    checkpoint_path.write_bytes(b"checkpoint")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    manifest = {
        "purpose": "offline_research_only",
        "checkpoint_file": checkpoint_path.name,
        "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "metadata_file": metadata_path.name,
        "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fake_torch = types.ModuleType("torch")
    fake_torch.load = lambda *args, **kwargs: checkpoint_data
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    class MismatchedModel:
        def load_state_dict(self, state_dict, strict):
            raise RuntimeError("size mismatch for classifier.weight")
    monkeypatch.setattr(model_module, "build_skin_classifier", lambda **kwargs: MismatchedModel())

    with pytest.raises(ValueError, match="weights do not match the selected architecture"):
        load_skin_research_model(str(checkpoint_path.resolve()))



def test_skin_loader_rejects_relative_checkpoint_path():
    from ml.skin_image.inference import load_skin_research_model

    with pytest.raises(ValueError, match="absolute"):
        load_skin_research_model("model.pt")


def test_skin_loader_rejects_manifest_symlink(tmp_path):
    import json
    from ml.skin_image.inference import load_skin_research_model

    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint")
    metadata = tmp_path / "model_metadata.json"
    metadata.write_text(json.dumps({
        "intended_use": "offline_research_only",
        "clinical_validation": False,
    }), encoding="utf-8")
    target = tmp_path / "manifest-target.json"
    target.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "artifact_manifest.json"
    manifest.symlink_to(target)

    with pytest.raises(ValueError, match="non-symlink"):
        load_skin_research_model(str(checkpoint.resolve()))



def test_skin_loader_rejects_symlinked_parent_directory(tmp_path):
    import json
    from ml.skin_image.inference import load_skin_research_model

    actual = tmp_path / "actual"
    actual.mkdir()
    checkpoint = actual / "model.pt"
    checkpoint.write_bytes(b"checkpoint")
    (actual / "model_metadata.json").write_text(json.dumps({
        "intended_use": "offline_research_only",
        "clinical_validation": False,
    }), encoding="utf-8")
    (actual / "artifact_manifest.json").write_text("{}", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ValueError, match="directory path must not contain symlinks"):
        load_skin_research_model(str(linked / "model.pt"))



def test_skin_loader_hashes_checkpoint_with_streaming_reads(tmp_path, monkeypatch):
    import hashlib
    import json

    from ml.skin_image.inference import load_skin_research_model

    checkpoint = tmp_path / "skin_model.pt"
    metadata_path = tmp_path / "model_metadata.json"
    manifest_path = tmp_path / "artifact_manifest.json"
    checkpoint.write_bytes(b"checkpoint-bytes")
    metadata_path.write_text(
        json.dumps({
            "intended_use": "offline_research_only",
            "clinical_validation": False,
        }),
        encoding="utf-8",
    )
    manifest = {
        "purpose": "offline_research_only",
        "checkpoint_file": checkpoint.name,
        "checkpoint_sha256": hashlib.sha256(b"not-the-checkpoint").hexdigest(),
        "metadata_file": metadata_path.name,
        "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def reject_read_bytes(_self):
        raise AssertionError("Checkpoint integrity hashing must use bounded-memory reads")

    monkeypatch.setattr("pathlib.Path.read_bytes", reject_read_bytes)
    with pytest.raises(ValueError, match="checkpoint digest mismatch"):
        load_skin_research_model(str(checkpoint.resolve()))
