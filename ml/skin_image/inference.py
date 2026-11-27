"""Safety-gated inference helper for offline skin-image research.

This function is not a clinical diagnostic endpoint. The caller must supply a reviewed model,
class mapping, calibrated temperature and validation-selected abstention threshold.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from PIL import Image

from ml.skin_image.quality import ImageQualityPolicy, inspect_image_quality


def _sha256_file(path: "Path", chunk_size: int = 1024 * 1024) -> str:
    """Hash a model artifact incrementally to bound peak memory usage."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()



def validate_skin_checkpoint(
    checkpoint: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate checkpoint identity and calibration before constructing an inference model."""
    import hashlib
    import json

    if not isinstance(checkpoint, dict):
        raise ValueError("Checkpoint must be a dictionary")
    required = {
        "model_state_dict", "class_names", "class_to_index", "architecture",
        "model_variant", "image_size", "normalization",
        "calibration_temperature", "abstention_threshold",
        "threshold_selection_partition", "experiment_config",
        "experiment_config_sha256", "manifest_sha256",
    }
    missing = required - set(checkpoint)
    if missing:
        raise ValueError(f"Checkpoint is missing required fields: {sorted(missing)}")

    manifest_digest = checkpoint["manifest_sha256"]
    if (
        not isinstance(manifest_digest, str)
        or len(manifest_digest) != 64
        or any(char not in "0123456789abcdef" for char in manifest_digest)
    ):
        raise ValueError("Checkpoint manifest_sha256 must be a lowercase SHA-256 hex digest")

    state_dict = checkpoint["model_state_dict"]
    if not isinstance(state_dict, Mapping) or not state_dict:
        raise ValueError("Checkpoint model_state_dict must be a non-empty mapping")
    for key, value in state_dict.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Checkpoint model_state_dict keys must be non-empty strings")
        # Accept PyTorch tensors without importing the optional PyTorch stack at module load.
        tensor = value
        if hasattr(tensor, "detach"):
            tensor = tensor.detach()
        if hasattr(tensor, "cpu"):
            tensor = tensor.cpu()
        if hasattr(tensor, "numpy"):
            try:
                tensor = tensor.numpy()
            except (TypeError, RuntimeError) as exc:
                raise ValueError(
                    f"Checkpoint model_state_dict entry {key!r} cannot be inspected"
                ) from exc
        try:
            array = np.asarray(tensor)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Checkpoint model_state_dict entry {key!r} is not a numeric tensor"
            ) from exc
        if array.size == 0 or not np.issubdtype(array.dtype, np.number):
            raise ValueError(
                f"Checkpoint model_state_dict entry {key!r} must be a non-empty numeric tensor"
            )
        if not np.isfinite(array).all():
            raise ValueError(
                f"Checkpoint model_state_dict entry {key!r} contains non-finite values"
            )

    names = checkpoint["class_names"]
    if (
        not isinstance(names, list) or len(names) < 2
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("Checkpoint class_names must be unique, non-empty labels")
    expected_mapping = {name: index for index, name in enumerate(names)}
    if checkpoint["class_to_index"] != expected_mapping:
        raise ValueError("Checkpoint class mapping does not match its ordered class names")

    architecture = checkpoint["architecture"]
    variant = checkpoint["model_variant"]
    if architecture not in {"mobilenet_v3", "resnet50", "efficientnet_b0"}:
        raise ValueError("Checkpoint architecture is unsupported")
    if (architecture == "mobilenet_v3" and variant not in {"large", "small"}) or (
        architecture != "mobilenet_v3" and variant != "default"
    ):
        raise ValueError("Checkpoint architecture and variant are inconsistent")
    image_size = checkpoint["image_size"]
    if isinstance(image_size, bool) or not isinstance(image_size, int) or image_size < 32:
        raise ValueError("Checkpoint image_size must be an integer of at least 32")
    if checkpoint["normalization"] != "ImageNet mean/std":
        raise ValueError("Checkpoint normalization is unsupported")
    temperature = checkpoint["calibration_temperature"]
    threshold = checkpoint["abstention_threshold"]
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float, np.integer, np.floating))
        or not np.isfinite(temperature) or temperature <= 0
    ):
        raise ValueError("Checkpoint calibration temperature must be positive and finite")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float, np.integer, np.floating))
        or not np.isfinite(threshold) or not 0 <= threshold <= 1
    ):
        raise ValueError("Checkpoint abstention threshold must be finite and between 0 and 1")
    if checkpoint["threshold_selection_partition"] != "validation_only":
        raise ValueError("Checkpoint threshold must be selected on validation data only")

    config = checkpoint["experiment_config"]
    if not isinstance(config, dict):
        raise ValueError("Checkpoint experiment_config must be an object")
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != checkpoint["experiment_config_sha256"]:
        raise ValueError("Checkpoint experiment configuration digest does not match")
    if (
        config.get("architecture") != architecture
        or config.get("variant") != variant
        or config.get("image_size") != image_size
    ):
        raise ValueError("Checkpoint configuration does not match model metadata")

    governance = config.get("dataset_governance")
    required_governance_reviews = (
        "license_review", "permitted_use_review", "privacy_review", "label_review",
        "clinical_reviewer_signoff",
    )
    if not isinstance(governance, dict):
        raise ValueError("Checkpoint is missing approved dataset governance provenance")
    if (
        not isinstance(governance.get("dataset_id"), str)
        or not governance["dataset_id"].strip()
        or governance.get("approval_status") != "research_only_approved"
        or governance.get("image_domain") not in {"dermoscopy", "clinical_phone_photo", "mixed"}
        or not isinstance(governance.get("source_url"), str)
        or not governance["source_url"].startswith("https://")
        or not isinstance(governance.get("version"), str)
        or not governance["version"].strip()
        or not isinstance(governance.get("license"), str)
        or governance["license"].strip().lower() in {
            "unknown", "unknown_pending_source_review", "none", "n/a", "not reviewed"
        }
        or not isinstance(governance.get("registry_sha256"), str)
        or len(governance["registry_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in governance["registry_sha256"])
        or not isinstance(governance.get("governance_reviews"), dict)
        or any(
            governance["governance_reviews"].get(field) != "approved"
            for field in required_governance_reviews
        )
    ):
        raise ValueError("Checkpoint dataset governance provenance is incomplete or unapproved")

    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ValueError("Model metadata must be a JSON object")
        comparisons = {
            "architecture": architecture,
            "variant": variant,
            "class_names": names,
            "class_to_index": expected_mapping,
            "image_size": image_size,
            "manifest_sha256": checkpoint.get("manifest_sha256"),
            "experiment_config_sha256": digest,
            "calibration_temperature": temperature,
            "abstention_threshold": threshold,
            "threshold_selection_partition": "validation_only",
            "dataset_governance": governance,
        }
        for key, expected in comparisons.items():
            if metadata.get(key) != expected:
                raise ValueError(f"Checkpoint and model metadata disagree on {key}")
        normalization = metadata.get("normalization")
        if not isinstance(normalization, dict) or (
            normalization.get("name") != "ImageNet"
            or normalization.get("mean") != [0.485, 0.456, 0.406]
            or normalization.get("std") != [0.229, 0.224, 0.225]
        ):
            raise ValueError("Model metadata normalization is unsupported")
        if metadata.get("clinical_validation") is not False:
            raise ValueError("Skin research artifact must not claim clinical validation")
        if metadata.get("intended_use") != "offline_research_only":
            raise ValueError("Skin artifact is not marked for offline research only")

    return {
        "class_names": list(names),
        "architecture": architecture,
        "variant": variant,
        "image_size": image_size,
        "temperature": float(temperature),
        "minimum_confidence": float(threshold),
    }



def load_skin_research_model(checkpoint_path: str | "Path", *, device: str = "cpu"):
    """Load a skin research checkpoint only after adjacent manifest and metadata verification.

    Only load artifacts from trusted, access-controlled storage. PyTorch's weights_only mode
    reduces pickle exposure but does not establish artifact authenticity; SHA-256 detects
    accidental or unauthorized byte changes only when the manifest itself is trusted.
    """
    import hashlib
    import json
    from pathlib import Path

    path = Path(checkpoint_path)
    if not path.is_absolute():
        raise ValueError("Checkpoint path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Checkpoint must be a regular non-symlink file")
    root = path.parent
    if any(directory.is_symlink() for directory in (root, *root.parents)):
        raise ValueError("Checkpoint directory path must not contain symlinks")
    metadata_path = root / "model_metadata.json"
    manifest_path = root / "artifact_manifest.json"
    for candidate, label in (
        (metadata_path, "Model metadata"),
        (manifest_path, "Artifact manifest"),
    ):
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"{label} must be a regular non-symlink file")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Skin artifact metadata or manifest is unreadable") from exc
    if not isinstance(metadata, dict) or not isinstance(manifest, dict):
        raise ValueError("Skin artifact metadata and manifest must be JSON objects")
    if manifest.get("purpose") != "offline_research_only":
        raise ValueError("Skin artifact manifest is not marked offline research only")
    if metadata.get("intended_use") != "offline_research_only" or metadata.get("clinical_validation") is not False:
        raise ValueError("Skin artifact metadata does not meet research-only requirements")
    if manifest.get("checkpoint_file") != path.name:
        raise ValueError("Skin artifact manifest checkpoint filename does not match")
    if manifest.get("metadata_file") != metadata_path.name:
        raise ValueError("Skin artifact manifest metadata filename does not match")

    def verify_digest(file_path: Path, expected: Any, label: str) -> None:
        if not isinstance(expected, str) or len(expected) != 64 or any(
            char not in "0123456789abcdef" for char in expected
        ):
            raise ValueError(f"Skin artifact {label} digest is invalid")
        actual = _sha256_file(file_path)
        if actual != expected:
            raise ValueError(f"Skin artifact {label} digest mismatch")

    verify_digest(path, manifest.get("checkpoint_sha256"), "checkpoint")
    verify_digest(metadata_path, manifest.get("metadata_sha256"), "metadata")

    try:
        import pickle
        import torch
    except ImportError as exc:
        raise RuntimeError("Install the optional skin dependencies from ml/requirements-skin.txt") from exc

    try:
        checkpoint = torch.load(path, map_location=device, weights_only=True)
    except (OSError, EOFError, pickle.UnpicklingError, RuntimeError, ValueError, TypeError) as exc:
        raise ValueError("Skin checkpoint could not be loaded safely") from exc
    settings = validate_skin_checkpoint(checkpoint, metadata)
    from ml.skin_image.model import build_skin_classifier

    model = build_skin_classifier(
        num_classes=len(settings["class_names"]),
        architecture=settings["architecture"],
        variant=settings["variant"],
        pretrained=False,
    )
    try:
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    except RuntimeError as exc:
        raise ValueError("Skin checkpoint weights do not match the selected architecture") from exc
    model.to(device)
    model.eval()
    return {
        "model": model,
        "settings": settings,
        "metadata": metadata,
        "status": "research_model_loaded",
        "intended_use": "offline_research_only",
    }


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
    except ImportError as exc:
        raise RuntimeError(
            "Install the optional skin dependencies from ml/requirements-skin.txt"
        ) from exc

    from ml.skin_image.data import build_image_transform, prepare_rgb_image
    from ml.skin_image.selective import apply_abstention

    canvas = prepare_rgb_image(image, image_size)
    transform = build_image_transform(training=False, image_size=image_size)
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
