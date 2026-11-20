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

The three-way comparison runner now integrates the validation-only calibration and threshold workflow.
It selects a candidate by validation macro-F1, fits scalar temperature using the selected model's
validation probabilities, derives the technical coverage cutoff from validation only, freezes the
choices, and evaluates the test partition once. The report contains raw and calibrated test
metrics, calibration metrics, coverage and accepted-subset performance. The selected local artifact
stores the vectorizer, estimator, label encoder, fitted temperature and threshold together.

A maximum temperature-scaled model score is not a disease probability or medical certainty.
Abstention reduces forced predictions but does not make the remaining predictions clinically safe.
These utilities are research-only and require representative, independently reviewed data.

A maximum temperature-scaled model score is not a disease probability or medical certainty.
Abstention reduces forced predictions but does not make the remaining predictions clinically safe.
These utilities are research-only and require representative, independently reviewed data.
