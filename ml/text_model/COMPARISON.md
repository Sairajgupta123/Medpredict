# Symptom-text model comparison

The controlled exploratory comparison supports:
- TF-IDF word and character n-grams + Logistic Regression
- TF-IDF word and character n-grams + Random Forest
- Optional XGBoost (install `ml/requirements-text-boosted.txt` and pass
  `--include-xgboost`)

All vectorizers are fitted only on the training partition. All candidate models use the same
group-aware split, label encoding and feature representation. Class weights are enabled for
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

## Interpretation safeguards

The current comparison uses one held-out partition for exploratory ranking. Repeatedly comparing
candidates on that partition introduces selection bias; the top score is not an unbiased final
performance estimate. Freeze the selected model and evaluate it once on a new, untouched external
cohort with patient/source grouping and class coverage. Review per-class sensitivity, specificity,
false negatives, calibration and subgroup performance with qualified reviewers.

The saved joblib bundles are untrusted-code-capable serialization artifacts: never load one from an
untrusted source. All outputs are research-only and are not connected to the prediction API.
