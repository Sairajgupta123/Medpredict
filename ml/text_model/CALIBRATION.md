# Text-model calibration and selective prediction

`ml.text_model.calibration` provides:
- Scalar temperature fitting from validation-set class probabilities.
- Temperature-scaled probability transformation.
- Negative log likelihood, multiclass Brier score and top-label ECE.
- Confidence-threshold abstention with explicit coverage reporting.
- Validation-based threshold selection for a requested technical coverage target.

## Required evaluation protocol

1. Train the selected candidate using training data.
2. Select model settings using training/validation data only.
3. Generate probabilities on a separate validation partition.
4. Fit the temperature and select the abstention threshold on validation data only.
5. Freeze both values and evaluate once on an untouched external test cohort.
6. Report discrimination, calibration, coverage, per-class sensitivity/specificity and subgroup results.

The current exploratory comparison runner does not yet create a dedicated validation partition or
wire these helpers into training. Do not fit calibration or choose thresholds on the comparison
test partition. The helper is not connected to the backend or user interface.

A maximum temperature-scaled model score is not a disease probability or medical certainty.
Abstention reduces forced predictions but does not make the remaining predictions clinically safe.
These utilities are research-only and require representative, independently reviewed data.
