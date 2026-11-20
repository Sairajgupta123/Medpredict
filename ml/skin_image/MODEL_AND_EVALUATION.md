# Skin model factory and evaluation

The optional model factory supports MobileNetV3-Large and MobileNetV3-Small. Pretrained ImageNet
weights are opt-in; enabling them may download external weights. No pretrained weights are
downloaded by default and no model has been trained as part of this repository change.

```python
from ml.skin_image.model import build_mobilenet_v3

model = build_mobilenet_v3(num_classes=6, variant="large", pretrained=False)
```

Use `ml.skin_image.metrics.classification_metrics` to calculate macro-F1, balanced accuracy,
confusion matrix and per-class precision/recall/F1. The caller must supply the exact class-name
order used by the saved label mapping.

The offline trainer uses patient-grouped class-aware partitions, fits temperature and selects an
abstention threshold using validation data only, then reports discrimination, calibration and
selective metrics on the untouched test partition. These helpers remain research scaffolding:
out-of-distribution detection, external validation, subgroup analysis and clinical safety review
are still required. Do not expose model outputs to users.
