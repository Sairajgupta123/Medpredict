# Skin-image preprocessing research scaffold

This module is for controlled offline experiments only. It does not diagnose skin conditions and
must not be exposed as a patient-facing prediction endpoint.

## Optional dependencies

Install the general ML requirements and then the optional PyTorch stack:

```bash
pip install -r ml/requirements.txt
pip install -r ml/requirements-skin.txt
```

The PyTorch/torchvision versions are intentionally isolated from the lightweight text pipeline.
Use a Python/PyTorch wheel combination supported by the official PyTorch installation selector
for your operating system and accelerator.

## Manifest contract

The CSV must include:
- `image_path`: path relative to the private image root
- `label`: reviewed dataset label
- `patient_id`: required for the patient-grouped split utility

Optional columns such as `image_id` and `lesion_id` can remain in the private manifest. Do not
pass patient identifiers to the model, print them, commit them, or include them in experiment logs.

## Patient-level split

```python
import pandas as pd
from ml.skin_image.splits import patient_grouped_split

manifest = pd.read_csv("private_manifest.csv")
splits = patient_grouped_split(manifest)
train = manifest.loc[list(splits.train)]
validation = manifest.loc[list(splits.validation)]
test = manifest.loc[list(splits.test)]
```

Default target proportions are 70/15/15. GroupShuffleSplit makes proportions approximate because
patients, not individual images, are the splitting unit. The utility refuses blank patient IDs
and fewer than three distinct patients. It does not guarantee that every class appears in every
partition; inspect class/group coverage before training and redesign the evaluation if coverage is
insufficient. If patient IDs are unavailable, do not claim patient-independent evaluation.

## Preprocessing policy

- Apply EXIF orientation and decode with Pillow.
- Convert to RGB and reject corrupt or extremely small images.
- Preserve aspect ratio using a fixed-size neutral-gray padded canvas.
- Normalize using ImageNet mean and standard deviation for transfer-learning experiments.
- Training-only augmentation is limited to horizontal flips and small rotations. No color jitter is
  applied because color may carry clinically relevant visual information.
- Validation and test data receive no random augmentation.

## Model input

`SkinImageDataset` returns `(image_tensor, integer_label)`. The label mapping must be saved with
the experiment artifact and reused unchanged for validation and inference. Patient IDs are never
returned.

## Current limitations

This scaffold has not been run against an approved real dataset. The chosen input size, padding,
augmentation and normalization are starting assumptions for controlled research, not clinically
validated preprocessing. Dataset-specific review and clinician input are required. The module
does not detect unsupported image modalities, out-of-distribution images, or diagnostic uncertainty.

## Model factory and metrics

`ml.skin_image.model.build_mobilenet_v3` provides MobileNetV3-Large and MobileNetV3-Small
classifier factories. Pretrained weights are opt-in and may download external artifacts.
`ml.skin_image.metrics.classification_metrics` reports macro-F1, balanced accuracy, confusion
matrix and per-class metrics.

See `MODEL_AND_EVALUATION.md`. No training run, benchmark result or clinical validation is
claimed. The current preprocessing and model factory are research scaffolding only.
