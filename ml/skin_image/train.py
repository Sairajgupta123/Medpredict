"""Offline training entry point for the skin-image research baseline.

This script requires a reviewed dataset and a private CSV manifest. It does not download data.
The final test partition is evaluated once after selecting the best validation macro-F1 checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


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
) -> dict[str, Any]:
    """Train a supported image architecture using identical split and evaluation rules."""
    if epochs < 1 or batch_size < 1 or learning_rate <= 0 or num_workers < 0:
        raise ValueError("epochs, batch_size and learning_rate must be positive")
    if not manifest_path.is_file():
        raise FileNotFoundError("Manifest file does not exist")
    if not image_root.is_dir():
        raise NotADirectoryError("Image root directory does not exist")

    manifest = pd.read_csv(manifest_path)
    required = {"image_path", "label", "patient_id"}
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"Training manifest is missing columns: {sorted(missing)}")
    manifest = manifest.copy()
    manifest["label"] = manifest["label"].fillna("").astype(str).str.strip()
    if manifest["label"].eq("").any():
        raise ValueError("Training manifest contains blank labels")

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
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
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
        "manifest_sha256": manifest_digest,
    }
    config_json = json.dumps(experiment_config, sort_keys=True, separators=(",", ":"))
    config_digest = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
    (output_dir / "experiment_config.json").write_text(
        json.dumps(experiment_config, indent=2), encoding="utf-8"
    )
    best_macro_f1 = -1.0
    best_epoch = 0
    history: list[dict[str, float]] = []
    model_slug = architecture if variant == "default" else f"{architecture}_{variant}"
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
                    "calibration_temperature": calibration_temperature
                    if "calibration_temperature" in locals() else None,
                    "abstention_threshold": abstention_threshold
                    if "abstention_threshold" in locals() else None,
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
        minimum_coverage=0.90,
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

    def class_support(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
        grouped = frame.groupby("label", sort=True)
        return {
            str(label): {
                "image_count": int(grouped.size().loc[label]),
                "patient_count": int(grouped["patient_id"].nunique().loc[label]),
            }
            for label in grouped.size().index
        }

    report = {
        "status": "research_experiment_only",
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
        "manifest_sha256": manifest_digest,
        "experiment_config_sha256": config_digest,
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
    (output_dir / "model_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
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
