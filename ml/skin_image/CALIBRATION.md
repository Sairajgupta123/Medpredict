# Probability calibration for skin-image experiments

The offline skin trainer integrates scalar temperature scaling and selective prediction.

## Implemented training flow

1. Train the candidate model using the training partition.
2. Select the checkpoint using validation macro-F1 only.
3. Reload the selected checkpoint and generate validation logits.
4. Fit a single positive temperature by minimizing validation negative log likelihood.
5. Convert validation logits to calibrated scores and select a confidence cutoff targeting 90% technical validation coverage.
6. Freeze both values and evaluate discrimination, calibration and selective coverage on the untouched test partition.
7. Store the fitted temperature and threshold in the model checkpoint and metadata.

The report includes validation/test NLL, multiclass Brier score, top-label ECE, and test selective coverage and accepted-set metrics. The threshold selection target is configurable in code at present and is not a clinical safety target.

## Reproducibility and interpretation

- Temperature and threshold selection use validation data only.
- Test labels and logits do not influence checkpoint selection, calibration fitting or threshold selection.
- Report coverage together with accepted-set performance; abstaining on difficult cases can make accepted-set metrics look artificially strong.
- ECE depends on bin count and sample size; report the binning method.
- Temperature scaling does not guarantee subgroup calibration, out-of-distribution reliability or safety on unsupported image modalities.

All metrics are research-only. No trained model or clinical performance claim is provided by this repository alone.
