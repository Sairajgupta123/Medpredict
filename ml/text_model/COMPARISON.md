# Symptom-text model comparison

The comparison runner supports:
- TF-IDF word and character n-grams + Logistic Regression
- TF-IDF word and character n-grams + Random Forest
- Optional XGBoost (install `ml/requirements-text-boosted.txt` and pass
  `--include-xgboost`)

All candidates use one shared train/validation/test partitioning strategy and feature
representation. Vectorizers are fitted on training text only. Class weights are enabled for
Logistic Regression and Random Forest.

## Run

```bash
python -m ml.text_model.compare_models --data ml/datasets/curated/text_symptoms.csv --output-dir ml/artifacts/text_comparison
```

To include XGBoost:

```bash
python -m pip install -r ml/requirements-text-boosted.txt
python -m ml.text_model.compare_models --data ml/datasets/curated/text_symptoms.csv --output-dir ml/artifacts/text_comparison --include-xgboost
```

The default split reserves 20% for validation and 20% for final test. Candidate selection uses
validation macro-F1 only. Temperature scaling and a confidence cutoff targeting 90% validation
coverage are fitted/selected using validation predictions only. Override the target with
`--target-validation-coverage`; an explicit fixed threshold can be supplied with
`--minimum-confidence`.

Only after the selected candidate, calibration temperature and abstention threshold are frozen
does the runner evaluate the final test partition. Test metrics are not used to rank candidates or
select thresholds. The report includes raw and calibrated discrimination metrics, calibration
metrics, selective coverage and accepted-subset metrics. A target coverage is not a target accuracy
or a clinical safety guarantee.

## Grouping and limitations

A trustworthy split requires a reviewed `group_id` representing patient/source identity. If it is
missing, the current helper tries to keep duplicate normalized symptom descriptions together, then
falls back to a stratified row split with an explicit provisional warning. Neither fallback can
rule out patient/source leakage. The runner fails if any partition lacks a class rather than
silently reporting incomplete class coverage.

Review per-class support, sensitivity, specificity, false negatives, calibration, subgroup
performance and external generalization with qualified reviewers. A separate untouched external
cohort is still required for independent validation.

The saved joblib bundle is a serialization artifact capable of executing code when loaded: never
load one from an untrusted source. After deserialization, `ml.text_model.inference.validate_text_model_bundle`
checks the required inference components, fitted estimator class indices, label-encoder order,
research-only purpose marker, and finite calibration/abstention settings. This validation happens
after deserialization and therefore does not make an untrusted joblib file safe to load. All outputs
are research-only and are not connected to the prediction API or approved for clinical use.

## Experiment output safety

The comparison runner refuses to overwrite an existing report or known candidate artifact in
the selected output directory. Use a new, empty output directory for each experiment. Move or
archive previous results explicitly before reusing a directory; the runner does not delete or
replace prior experiment evidence.

The simpler baseline trainer applies the same protection to `model.joblib` and `metrics.json`.
Joblib files can execute code during deserialization, so load only artifacts from trusted storage.

## Experiment provenance

The comparison report records the raw dataset SHA-256, validated row count, class labels,
partition sizes and split methods, random seed, model-selection and calibration settings,
runtime versions, and a canonical experiment-configuration SHA-256. The configuration digest
is generated from sorted JSON keys, so equivalent configurations produce the same digest.

The baseline trainer records the same dataset fingerprint and configuration digest alongside
its split details and Python, NumPy, pandas and scikit-learn versions. These fingerprints help
identify the exact input file and settings associated with an experiment; they do not prove
that a dataset is clinically valid, licensed, de-identified, or trustworthy.
