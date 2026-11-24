"""Run a controlled architecture comparison on identical patient-grouped splits.

Architectures are ranked by validation macro-F1 only. Test metrics are retained for reporting and
must never be used to select a winning architecture. This is an offline research utility.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ml.skin_image.train import train_skin_model


DEFAULT_CANDIDATES = (
    ("mobilenet_v3", "large"),
    ("mobilenet_v3", "small"),
    ("resnet50", "default"),
    ("efficientnet_b0", "default"),
)


def compare_architectures(
    manifest_path: Path,
    image_root: Path,
    output_dir: Path,
    *,
    candidates: tuple[tuple[str, str], ...] = DEFAULT_CANDIDATES,
    epochs: int = 10,
    batch_size: int = 16,
    learning_rate: float = 1e-4,
    seed: int = 42,
    pretrained: bool = False,
    num_workers: int = 0,
    target_validation_coverage: float = 0.90,
    dataset_registry_path: Path | None = None,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    """Train candidates with shared settings and rank only by validation macro-F1."""
    if not candidates:
        raise ValueError("At least one architecture candidate is required")
    if len(set(candidates)) != len(candidates):
        raise ValueError("Architecture candidates must be unique")
    output_dir.mkdir(parents=True, exist_ok=True)

    experiments: list[dict[str, Any]] = []
    for architecture, variant in candidates:
        slug = architecture if variant == "default" else f"{architecture}_{variant}"
        report = train_skin_model(
            manifest_path,
            image_root,
            output_dir / slug,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            seed=seed,
            variant=variant,
            pretrained=pretrained,
            num_workers=num_workers,
            architecture=architecture,
            target_validation_coverage=target_validation_coverage,
            dataset_registry_path=dataset_registry_path,
            dataset_id=dataset_id,
        )
        experiments.append(
            {
                "architecture": architecture,
                "variant": variant,
                "best_epoch": report["best_epoch"],
                "best_validation_macro_f1": report["best_validation_macro_f1"],
                "test_macro_f1_report_only": report["test_metrics"]["macro_f1"],
                "test_metrics_must_not_select_winner": True,
                "report_path": f"{slug}/experiment_report.json",
                "metadata_path": f"{slug}/model_metadata.json",
            }
        )

    ranking = sorted(
        experiments,
        key=lambda item: item["best_validation_macro_f1"],
        reverse=True,
    )
    summary = {
        "status": "research_comparison_only",
        "ranking_metric": "best_validation_macro_f1",
        "test_metrics_used_for_ranking": False,
        "shared_settings": {
            "seed": seed,
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "pretrained": pretrained,
            "split_strategy": "class_aware_patient_grouped_70_15_15_candidate_search",
            "target_validation_coverage": target_validation_coverage,
        },
        "ranking": ranking,
        "limitations": [
            "Validation ranking can be noisy and is not external validation.",
            "Do not select a winner using test metrics.",
            "Candidate runs share the same patient-grouped split seed.",
            "No clinical validation or deployment approval is implied.",
        ],
    }
    (output_dir / "comparison_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


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
    parser.add_argument("--pretrained", action="store_true")
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--target-validation-coverage", type=float, default=0.90)
    args = parser.parse_args()

    result = compare_architectures(
        args.manifest,
        args.image_root,
        args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        seed=args.seed,
        pretrained=args.pretrained,
        num_workers=args.num_workers,
        target_validation_coverage=args.target_validation_coverage,
        dataset_registry_path=args.dataset_registry,
        dataset_id=args.dataset_id,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "ranking_metric": result["ranking_metric"],
                "winner_by_validation_only": (
                    result["ranking"][0]["architecture"],
                    result["ranking"][0]["variant"],
                ),
                "summary_path": str(args.output_dir / "comparison_summary.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
