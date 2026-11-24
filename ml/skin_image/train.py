"""Offline training entry point for the skin-image research baseline.

This script requires a reviewed dataset and a private CSV manifest. It does not download data.
The final test partition is evaluated once after selecting the best validation macro-F1 checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash an artifact incrementally to keep peak memory bounded."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_research_dataset_approval(
    registry_path: Path, dataset_id: str
) -> dict[str, Any]:
    """Require explicit source-specific governance sign-off before model training."""
    from ml.datasets.registry import validate_dataset_record

    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("A non-empty dataset_id is required for training")
    if not registry_path.is_file():
        raise FileNotFoundError("An approved dataset registry file is required for training")
    registry_digest = _sha256_file(registry_path)
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Dataset registry is unreadable; training is blocked") from exc
    if not isinstance(registry, dict) or not isinstance(registry.get("datasets"), list):
        raise ValueError("Dataset registry must contain a datasets array")

    matches = [
        record for record in registry["datasets"]
        if isinstance(record, dict) and record.get("dataset_id") == dataset_id
    ]
    if len(matches) != 1:
        raise ValueError("Dataset ID must match exactly one registry record")
    record = matches[0]
    validation = validate_dataset_record(record)
    if not validation["record_complete"]:
        raise ValueError("Dataset registry record is incomplete or invalid; training is blocked")

    required_approvals = (
        "license_review", "permitted_use_review", "privacy_review", "label_review",
        "clinical_reviewer_signoff",
    )
    if any(record.get(field) != "approved" for field in required_approvals):
        raise ValueError("All dataset governance reviews and clinical sign-off must be approved")
    if record.get("approval_status") != "research_only_approved":
        raise ValueError("Dataset must be explicitly approved for research-only use")
    if record.get("modality") != "image" or record.get("image_domain") not in {
        "dermoscopy", "clinical_phone_photo", "mixed"
    }:
        raise ValueError("Dataset registry record is not approved for skin-image training")
    if str(record.get("license", "")).strip().lower() in {
        "unknown", "unknown_pending_source_review", "none", "n/a", "not reviewed"
    }:
        raise ValueError("A specific reviewed dataset license is required for training")

    if _sha256_file(registry_path) != registry_digest:
        raise ValueError("Dataset registry changed during approval checks; training is blocked")

    return {
        "dataset_id": dataset_id,
        "source_url": record["source_url"],
        "version": record["version"],
        "license": record["license"],
        "image_domain": record["image_domain"],
        "approval_status": record["approval_status"],
        "governance_reviews": {field: record[field] for field in required_approvals},
        "registry_sha256": registry_digest,
    }


def ensure_skin_artifacts_do_not_exist(
    output_dir: Path, filenames: list[str]
) -> None:
    """Refuse to replace evidence from an earlier skin-image experiment."""
    if output_dir.exists() and not output_dir.is_dir():
        raise FileExistsError(f"Output path is not a directory: {output_dir}")
    existing = (
        [name for name in filenames if (output_dir / name).exists()]
        if output_dir.is_dir()
        else []
    )
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing skin experiment artifact(s): "
            f"{', '.join(sorted(existing))}. Choose a new output directory or "
            "move the previous artifacts explicitly."
        )


def _seed_everything(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def _run_epoch(model, loader, criterion, device, optimizer=None):
    import torch

    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    actual: list[int] = []
    predicted: list[int] = []
    collected_logits: list[np.ndarray] = []

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        if training:
            optimizer.zero_grad(set_to_none=True)

        with torch.set_grad_enabled(training):
            logits = model(images)
            loss = criterion(logits, labels)
            if training:
                loss.backward()
                optimizer.step()

        total_loss += float(loss.item()) * int(labels.size(0))
        actual.extend(labels.detach().cpu().tolist())
        predicted.extend(logits.argmax(dim=1).detach().cpu().tolist())
        if not training:
            collected_logits.append(logits.detach().cpu().numpy())

    if not actual:
        raise ValueError("A training/evaluation partition is empty")
    logits_array = (
        np.concatenate(collected_logits, axis=0)
        if collected_logits
        else np.empty((0, 0), dtype=np.float32)
    )
    return total_loss / len(actual), actual, predicted, logits_array


def train_skin_model(
    manifest_path: Path,
    image_root: Path,
    output_dir: Path,
    *,
    epochs: int = 10,
    batch_size: int = 16,
    learning_rate: float = 1e-4,
    seed: int = 42,
    variant: str = "large",
    pretrained: bool = False,
    num_workers: int = 0,
    architecture: str = "mobilenet_v3",
    target_validation_coverage: float = 0.90,
    dataset_registry_path: Path | None = None,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    """Train a supported image architecture using identical split and evaluation rules."""
    integer_parameters = {
        "epochs": epochs,
        "batch_size": batch_size,
        "seed": seed,
        "num_workers": num_workers,
    }
    for name, value in integer_parameters.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
    if epochs < 1 or batch_size < 1 or num_workers < 0:
        raise ValueError("epochs and batch_size must be positive; num_workers cannot be negative")
    if (
        isinstance(learning_rate, bool)
        or not isinstance(learning_rate, (int, float, np.integer, np.floating))
        or not np.isfinite(learning_rate)
        or learning_rate <= 0
    ):
        raise ValueError("learning_rate must be a positive finite number")
    if (
        isinstance(target_validation_coverage, bool)
        or not isinstance(target_validation_coverage, (int, float, np.integer, np.floating))
        or not np.isfinite(target_validation_coverage)
        or not 0 < target_validation_coverage <= 1
    ):
        raise ValueError("target_validation_coverage must be a finite number in (0, 1]")
    if architecture not in {"mobilenet_v3", "resnet50", "efficientnet_b0"}:
        raise ValueError("architecture must be mobilenet_v3, resnet50 or efficientnet_b0")
    if (architecture == "mobilenet_v3" and variant not in {"large", "small"}) or (
        architecture != "mobilenet_v3" and variant != "default"
    ):
        raise ValueError("variant is inconsistent with the selected architecture")
    if not manifest_path.is_file():
        raise FileNotFoundError("Manifest file does not exist")
    if not image_root.is_dir():
        raise NotADirectoryError("Image root directory does not exist")

    model_slug = architecture if variant == "default" else f"{architecture}_{variant}"
    ensure_skin_artifacts_do_not_exist(
        output_dir,
        [
            "experiment_config.json",
            f"skin_{model_slug}_best.pt",
            "model_metadata.json",
            "experiment_report.json",
        ],
    )

    # Hash the exact manifest artifact before training; never load the full CSV bytes into RAM.
    manifest_digest = _sha256_file(manifest_path)
    manifest = pd.read_csv(manifest_path)
    required = {"image_path", "label", "patient_id"}
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"Training manifest is missing columns: {sorted(missing)}")
    manifest = manifest.copy()
    manifest["label"] = manifest["label"].fillna("").astype(str).str.strip()
    if manifest["label"].eq("").any():
        raise ValueError("Training manifest contains blank labels")

    # Enforce the same file-integrity and duplicate-content gate used during dataset intake.
    # This remains a technical gate only; it does not approve licensing or clinical labels.
    from ml.datasets.audit_skin_manifest import audit_skin_manifest

    intake_report = audit_skin_manifest(manifest_path, image_root, inspect_images=True)
    # The manifest is read more than once during preflight. Refuse to continue if
    # it changed after the digest was captured, so the checkpoint cannot claim
    # provenance for a different manifest than the one that was audited.
    if _sha256_file(manifest_path) != manifest_digest:
        raise ValueError("Training manifest changed during dataset preflight; training is blocked")
    readiness = intake_report["training_readiness"]
    if not readiness["ready_for_reviewer_signoff"]:
        reasons = ", ".join(readiness["blocking_reasons"])
        raise ValueError(
            "Skin dataset failed technical intake checks; training is blocked: "
            f"{reasons}"
        )
    if dataset_registry_path is None or dataset_id is None:
        raise ValueError(
            "An approved dataset registry and dataset_id are required; technical checks alone "
            "do not authorize training"
        )
    dataset_governance = require_research_dataset_approval(
        dataset_registry_path, dataset_id
    )

    from ml.skin_image.splits import patient_grouped_split

    splits = patient_grouped_split(manifest, random_state=seed)
    train_frame = manifest.loc[list(splits.train)].copy()
    validation_frame = manifest.loc[list(splits.validation)].copy()
    test_frame = manifest.loc[list(splits.test)].copy()

    class_names = sorted(train_frame["label"].unique().tolist())
    if len(class_names) < 2:
        raise ValueError("Training partition must contain at least two classes")
    class_to_index = {name: index for index, name in enumerate(class_names)}
    for name, frame in (
        ("validation", validation_frame),
        ("test", test_frame),
    ):
        unknown = set(frame["label"].unique()) - set(class_to_index)
        if unknown:
            raise ValueError(
                f"{name} partition contains labels absent from training partition"
            )

    # Load the optional deep-learning stack only after inexpensive manifest preflight checks.
    import torch
    import scipy
    import PIL
    from torch import nn
    from torch.utils.data import DataLoader

    from ml.skin_image.class_weights import calculate_class_weights
    from ml.skin_image.data import SkinImageDataset
    from ml.skin_image.metrics import classification_metrics
    from ml.skin_image.model import build_skin_classifier
    from ml.skin_image.calibration import calibration_metrics, fit_temperature
    from ml.skin_image.selective import (
        select_threshold_for_coverage,
        selective_classification_metrics,
    )
    from scipy.special import softmax

    _seed_everything(seed)
    train_dataset = SkinImageDataset(
        train_frame,
        image_root,
        label_to_index=class_to_index,
        training=True,
    )
    validation_dataset = SkinImageDataset(
        validation_frame,
        image_root,
        label_to_index=class_to_index,
        training=False,
    )
    test_dataset = SkinImageDataset(
        test_frame,
        image_root,
        label_to_index=class_to_index,
        training=False,
    )

    generator = torch.Generator()
    generator.manual_seed(seed)
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        generator=generator,
    )
    validation_loader = DataLoader(
        validation_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
    )
    test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_skin_classifier(
        num_classes=len(class_names),
        architecture=architecture,
        variant=variant,
        pretrained=pretrained,
    ).to(device)
    training_labels = [
        class_to_index[label] for label in train_frame["label"].tolist()
    ]
    weight_report = calculate_class_weights(
        training_labels,
        class_count=len(class_names),
    )
    class_weights = torch.tensor(
        weight_report["class_weights"],
        dtype=torch.float32,
        device=device,
    )
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)

    output_dir.mkdir(parents=True, exist_ok=True)
    experiment_config = {
        "architecture": architecture,
        "variant": variant,
        "pretrained": pretrained,
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": learning_rate,
        "seed": seed,
        "num_workers": num_workers,
        "image_size": 224,
        "optimizer": "AdamW",
        "loss": "weighted_cross_entropy",
        "checkpoint_selection_metric": "validation_macro_f1",
        "split_strategy": "class_aware_patient_grouped_70_15_15_candidate_search",
        "split_search_attempts": 64,
        "all_classes_required_in_each_partition": True,
        "target_validation_coverage": target_validation_coverage,
        "manifest_sha256": manifest_digest,
        "dataset_governance": dataset_governance,
    }
    config_json = json.dumps(experiment_config, sort_keys=True, separators=(",", ":"))
    config_digest = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
    (output_dir / "experiment_config.json").write_text(
        json.dumps(experiment_config, indent=2), encoding="utf-8"
    )
    best_macro_f1 = -1.0
    best_epoch = 0
    history: list[dict[str, float]] = []
    checkpoint_path = output_dir / f"skin_{model_slug}_best.pt"

    for epoch in range(1, epochs + 1):
        train_loss, _, _, _ = _run_epoch(
            model, train_loader, criterion, device, optimizer
        )
        validation_loss, y_true, y_pred, _ = _run_epoch(
            model, validation_loader, criterion, device
        )
        validation_metrics = classification_metrics(
            y_true, y_pred, class_names=class_names
        )
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": float(train_loss),
                "validation_loss": float(validation_loss),
                "validation_macro_f1": float(validation_metrics["macro_f1"]),
            }
        )
        if validation_metrics["macro_f1"] > best_macro_f1:
            best_macro_f1 = validation_metrics["macro_f1"]
            best_epoch = epoch
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "class_names": class_names,
                    "class_to_index": class_to_index,
                    "architecture": architecture,
                    "model_variant": variant,
                    "image_size": 224,
                    "normalization": "ImageNet mean/std",
                    "seed": seed,
                    "best_epoch": best_epoch,
                    "manifest_sha256": manifest_digest,
                    "experiment_config_sha256": config_digest,
                    "experiment_config": experiment_config,
                },
                checkpoint_path,
            )

    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["model_state_dict"])
    validation_loss, validation_targets, _, validation_logits = _run_epoch(
        model, validation_loader, criterion, device
    )
    test_loss, y_true, y_pred, test_logits = _run_epoch(
        model, test_loader, criterion, device
    )
    test_metrics = classification_metrics(
        y_true, y_pred, class_names=class_names
    )

    # Calibration and abstention are fitted only on the validation partition.
    calibration_temperature = fit_temperature(
        validation_logits, validation_targets
    )
    validation_probabilities = softmax(
        validation_logits / calibration_temperature, axis=1
    )
    threshold_selection = select_threshold_for_coverage(
        validation_probabilities,
        minimum_coverage=target_validation_coverage,
    )
    abstention_threshold = float(threshold_selection["threshold"])
    test_probabilities = softmax(test_logits / calibration_temperature, axis=1)
    validation_calibration = calibration_metrics(
        validation_logits, validation_targets,
        temperature=calibration_temperature,
    )
    test_calibration = calibration_metrics(
        test_logits, y_true, temperature=calibration_temperature,
    )
    test_selective_metrics = selective_classification_metrics(
        y_true, test_probabilities,
        minimum_confidence=abstention_threshold,
    )
    checkpoint["calibration_temperature"] = calibration_temperature
    checkpoint["abstention_threshold"] = abstention_threshold
    checkpoint["threshold_selection_partition"] = "validation_only"
    torch.save(checkpoint, checkpoint_path)

    def class_support(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
        grouped = frame.groupby("label", sort=True)
        return {
            str(label): {
                "image_count": int(grouped.size().loc[label]),
                "patient_count": int(grouped["patient_id"].nunique().loc[label]),
            }
            for label in grouped.size().index
        }

    runtime_versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pytorch": str(torch.__version__),
        "scipy": scipy.__version__,
        "pillow": PIL.__version__,
    }
    report = {
        "status": "research_experiment_only",
        "runtime_versions": runtime_versions,
        "manifest_file_name": manifest_path.name,
        "model": f"{architecture}-{variant}",
        "device": str(device),
        "seed": seed,
        "epochs_requested": epochs,
        "best_epoch": best_epoch,
        "best_validation_macro_f1": best_macro_f1,
        "test_loss": test_loss,
        "test_metrics": test_metrics,
        "calibration": {
            "temperature": calibration_temperature,
            "fit_partition": "validation_only",
            "validation_metrics": validation_calibration,
            "test_metrics": test_calibration,
        },
        "abstention": {
            "threshold_selection": threshold_selection,
            "selection_partition": "validation_only",
            "test_metrics": test_selective_metrics,
        },
        "class_names": class_names,
        "class_to_index": class_to_index,
        "training_class_balance": weight_report,
        "partition_row_counts": {
            "train": len(train_frame),
            "validation": len(validation_frame),
            "test": len(test_frame),
        },
        "partition_patient_counts": {
            "train": int(train_frame["patient_id"].nunique()),
            "validation": int(validation_frame["patient_id"].nunique()),
            "test": int(test_frame["patient_id"].nunique()),
        },
        "partition_class_support": {
            "train": class_support(train_frame),
            "validation": class_support(validation_frame),
            "test": class_support(test_frame),
        },
        "manifest_sha256": manifest_digest,
        "dataset_governance": dataset_governance,
        "experiment_config": experiment_config,
        "experiment_config_sha256": config_digest,
        "history": history,
        "limitations": [
            "No clinical validation is implied.",
            "Patient-grouped split proportions are approximate because patients are indivisible.",
            "Every class is required in every partition; this does not guarantee adequate sample support.",
            "Class coverage does not replace subgroup or external validation.",
            "The dataset license and label provenance must be reviewed separately.",
            "The test partition must not be used for model selection.",
        ],
    }
    metadata = {
        "artifact_format_version": 1,
        "model_name": report["model"],
        "architecture": architecture,
        "variant": variant,
        "class_names": class_names,
        "class_to_index": class_to_index,
        "image_size": 224,
        "normalization": {
            "name": "ImageNet",
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
        },
        "manifest_file_name": manifest_path.name,
        "manifest_sha256": manifest_digest,
        "dataset_governance": dataset_governance,
        "experiment_config_sha256": config_digest,
        "runtime_versions": runtime_versions,
        "checkpoint_file": checkpoint_path.name,
        "best_epoch": best_epoch,
        "selection_metric": "validation_macro_f1",
        "split_strategy": experiment_config["split_strategy"],
        "partition_class_support": report["partition_class_support"],
        "intended_use": "offline_research_only",
        "clinical_validation": False,
        "calibration_temperature": calibration_temperature,
        "abstention_threshold": abstention_threshold,
        "threshold_selection_partition": "validation_only",
    }
    metadata_path = output_dir / "model_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    artifact_manifest = {
        "purpose": "offline_research_only",
        "checkpoint_file": checkpoint_path.name,
        "checkpoint_sha256": _sha256_file(checkpoint_path),
        "metadata_file": metadata_path.name,
        "metadata_sha256": _sha256_file(metadata_path),
        "note": "SHA-256 checks byte consistency only; it is not a digital signature or proof of artifact authenticity.",
    }
    (output_dir / "artifact_manifest.json").write_text(
        json.dumps(artifact_manifest, indent=2), encoding="utf-8"
    )
    (output_dir / "experiment_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dataset-registry", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--architecture",
        choices=("mobilenet_v3", "resnet50", "efficientnet_b0"),
        default="mobilenet_v3",
    )
    parser.add_argument(
        "--variant",
        choices=("large", "small", "default"),
        default="large",
        help="MobileNetV3 variant; use 'default' for ResNet50/EfficientNet-B0",
    )
    parser.add_argument("--pretrained", action="store_true")
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--target-validation-coverage", type=float, default=0.90)
    args = parser.parse_args()

    report = train_skin_model(
        args.manifest,
        args.image_root,
        args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        seed=args.seed,
        variant=args.variant,
        pretrained=args.pretrained,
        architecture=args.architecture,
        num_workers=args.num_workers,
        target_validation_coverage=args.target_validation_coverage,
        dataset_registry_path=args.dataset_registry,
        dataset_id=args.dataset_id,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "best_epoch": report["best_epoch"],
                "test_macro_f1": report["test_metrics"]["macro_f1"],
                "report_path": str(args.output_dir / "experiment_report.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
