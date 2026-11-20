# Probability calibration for skin-image experiments

The `ml.skin_image.calibration` module provides scalar temperature scaling and multiclass
calibration metrics:

- `fit_temperature(validation_logits, validation_targets)` fits a positive temperature by
  minimizing validation negative log likelihood.
- `multiclass_nll(..., temperature=...)` computes multiclass negative log likelihood.
- `calibration_metrics(..., temperature=...)` reports NLL, multiclass Brier score and top-label
  expected calibration error (ECE).

## Correct evaluation protocol

1. Train the model using the training partition.
2. Select the checkpoint using validation performance.
3. Generate logits for that selected checkpoint on validation data.
4. Fit one temperature using validation logits and labels only.
5. Freeze the temperature and evaluate calibration metrics on untouched test logits.
6. Report discrimination, calibration and coverage together.

Never fit temperature on test data. ECE depends on bin count and sample size; report the chosen
binning method. Temperature scaling does not guarantee subgroup calibration, out-of-distribution
reliability or safety on unsupported image modalities.

This helper is not yet wired into the training runner. No calibration result is claimed. Model
scores remain research outputs, not disease probabilities or medical certainty.
