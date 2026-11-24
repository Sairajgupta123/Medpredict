# Skin-image preprocessing and training research scaffold

This module is for controlled offline experiments only. It does not diagnose skin conditions and
must not be exposed as a patient-facing prediction endpoint.

## Optional dependencies

Install the general ML requirements and then the optional PyTorch stack:

```bash
pip install -r ml/requirements.txt
pip install -r ml/requirements-skin.txt
```

Choose compatible PyTorch and torchvision wheels for your operating system and accelerator using
the official PyTorch installation selector.

## Private manifest contract

The CSV must include:
- `image_path`: path relative to the private image root
- `label`: reviewed dataset label
- `patient_id`: required for patient-grouped splitting

Do not pass patient identifiers to the model, print them, commit them, or include them in experiment
logs. Keep the manifest and images in approved private storage.

## Dataset governance gate

Technical file checks alone do not authorize model training. Before training, add a source-specific
record to a private dataset registry JSON file and obtain documented approval for the license,
permitted use, privacy, labels and clinical reviewer sign-off. The record must use
`approval_status: research_only_approved`, `modality: image`, and a known image domain
(`dermoscopy`, `clinical_phone_photo` or `mixed`). Unknown or placeholder licenses are rejected.
The registry record's `dataset_id` must match the training command exactly; duplicate IDs and
registry changes during validation are rejected. Approval must be performed by the responsible
human reviewers, never inferred from this software. Keep the registry private if it contains
restricted source or governance details.

## Run an offline research experiment

```bash
python -m ml.skin_image.train --manifest private_manifest.csv --image-root private_images --output-dir private_experiment --dataset-registry private_dataset_registry.json --dataset-id reviewed-skin-dataset-v1 --epochs 10 --target-validation-coverage 0.90
```

The registry must contain the matching record with all five review fields set to `approved`:
`license_review`, `permitted_use_review`, `privacy_review`, `label_review`, and
`clinical_reviewer_signoff`. A successful gate grants research-only training permission; it does
not establish clinical validity or permit deployment. The trainer records the dataset ID, registry
digest and approval summary in experiment configuration, metadata and report.

The trainer creates deterministic, class-aware patient-grouped 70/15/15 approximate partitions.
It requires every class to occur in at least three distinct patients and in every partition, then
searches candidate group splits to reduce row/patient proportion and class-distribution imbalance.
It supports MobileNetV3, ResNet50 and EfficientNet-B0, selects the checkpoint using validation
macro-F1, fits temperature and selects a configurable technical coverage threshold (default 90%)
on validation only, and evaluates the held-out test partition at the end. The target can be changed
with `--target-validation-coverage`. The test partition must not be used for model selection. The output
directory contains a checkpoint, experiment configuration, model metadata and aggregate report;
keep all artifacts outside Git because they may be large and subject to dataset license restrictions.
See EXPERIMENTS.md for the controlled architecture comparison runner.

## Important evaluation limitations

Patient-grouped proportions are approximate because patients are indivisible. The splitter requires
at least three distinct patients per class and guarantees every class appears in train, validation
and test; it searches candidate partitions to reduce distribution imbalance. Review image and
patient support counts before interpreting results. Class weighting, validation-only calibration
and validation-selected abstention are integrated. Validated out-of-distribution detection,
external validation and subgroup fairness analysis remain outstanding.

## Preprocessing

- Apply EXIF orientation, decode with Pillow and convert to RGB.
- Reject corrupt or extremely small images.
- Preserve aspect ratio using a fixed-size neutral-gray padded canvas.
- Normalize using ImageNet mean and standard deviation.
- Training-only augmentation uses horizontal flips and small rotations; validation/test have no
  random augmentation.
- No color jitter is used because color may carry clinically relevant information.

All settings are research starting points, not clinically validated preprocessing. The model factory,
trainer and metrics are not approved for patient-facing use.

## Image quality and prediction abstention

`ml.skin_image.quality.inspect_image_quality` provides configurable heuristic flags for low
resolution, extreme brightness/darkness, clipped pixels and possible blur. These thresholds are
not clinically validated and do not identify supported image modalities.

`ml.skin_image.selective.apply_abstention` returns no class (`None`) when the maximum model score
is below a supplied threshold. `selective_classification_metrics` reports coverage and accepted-set
performance. The maximum softmax score is not automatically calibrated and is not medical certainty.

See `QUALITY_AND_ABSTENTION.md`. Thresholds must be selected using validation data and evaluated
on an untouched test set. Calibration, validated out-of-distribution detection and modality checks
remain future work.

## Probability calibration

`ml.skin_image.calibration` adds validation-fitted scalar temperature scaling, negative log
likelihood, multiclass Brier score and top-label expected calibration error. Follow
`CALIBRATION.md`: fit temperature on validation logits only and evaluate on an untouched test set.
The trainer now fits temperature on the selected checkpoint's validation logits and evaluates
calibration metrics on the untouched test logits. The fitted temperature is stored with the
checkpoint and model metadata.

## Safety-gated research inference

`ml.skin_image.inference.predict_skin_image` performs image-quality screening before model
execution, applies the supplied temperature and abstention threshold, and returns a research class,
an uncertainty status, or an image-quality rejection. See `INFERENCE.md`.

The helper is not connected to the FastAPI backend. The caller must provide a trained model, exact
class order, validation-fitted temperature and validation-selected threshold. The offline trainer
stores these values in its checkpoint and model metadata. No model has been
trained, and this helper is not approved for patient-facing use.

## Class imbalance and per-class rates

The trainer calculates balanced inverse-frequency class weights from the training partition only
and supplies them to the cross-entropy loss. The experiment report records training class counts
and the resulting weights. Validation and test labels are never used to calculate these weights.

Evaluation reports one-vs-rest sensitivity (recall) and specificity for each class, alongside
macro-F1, balanced accuracy and the confusion matrix. Balanced accuracy averages sensitivity over
the full configured class list, so a class with no true samples contributes zero rather than being
silently omitted. Interpret every rate with its support count; a missing class in an evaluation
partition is not evidence of perfect performance. Weighting is an
experiment setting, not a guarantee of improved minority-class or clinical performance.

## Reproducible experiments and architecture comparison

The model factory supports MobileNetV3-Large, MobileNetV3-Small, ResNet50 and EfficientNet-B0.
The trainer records a configuration JSON, its SHA-256 digest, model metadata and the dataset-manifest
digest. Use `python -m ml.skin_image.compare_models` to run candidates with a shared split seed and
rank them by validation macro-F1 only. Test metrics are report-only and must never determine the
winner. See `EXPERIMENTS.md` for the evaluation protocol and artifact handling rules.
