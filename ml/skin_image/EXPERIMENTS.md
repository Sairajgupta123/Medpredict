# Reproducible skin model experiments and architecture comparison

## Supported candidate architectures

The shared model factory supports:
- MobileNetV3-Large
- MobileNetV3-Small
- ResNet50
- EfficientNet-B0

All candidates use the same 224px preprocessing contract and class mapping. Pretrained weights are
opt-in; enabling them may download weights from the upstream torchvision source. Record whether
pretraining was enabled and review the upstream weights' terms before use.

## Run a comparison

```bash
python -m ml.skin_image.compare_models --manifest private_manifest.csv --image-root private_images --output-dir private_comparison --epochs 10 --seed 42
```

The runner executes each candidate using the same manifest, deterministic class-aware patient-grouped
split seed and common training settings. Every class must occur in at least three distinct patients
and in each partition; the splitter searches candidate partitions to reduce class-distribution and
proportion imbalance. Each candidate writes its own checkpoint, experiment configuration, model
metadata and aggregate report. The trainer fits temperature and selects its technical coverage threshold from validation data only.
The comparison summary ranks candidates by best validation macro-F1. Test metrics remain report-only.

**Never choose the winning architecture from test metrics.** Test metrics are included for
transparent reporting only. If architecture selection or repeated tuning has exhausted the
validation set, use a new untouched external test cohort for final evaluation.

## Reproducibility artifacts

Each run writes:
- `experiment_config.json`: model, optimizer, loss, seed, split strategy and data-manifest digest
- `model_metadata.json`: architecture, class order, image normalization, checkpoint name and
  research-only intended-use marker
- `experiment_report.json`: training history, validation selection result and held-out metrics
- model checkpoint: state dictionary and the metadata needed to reconstruct the classifier

The SHA-256 digest identifies the exact manifest bytes but does not make the manifest public or
prove dataset provenance. Keep images, manifests, checkpoints and reports in access-controlled
storage. Do not commit patient-level data or model artifacts to the repository.

All results are experimental. No architecture is declared clinically suitable by this comparison.
