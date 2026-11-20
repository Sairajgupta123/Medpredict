# Model card: text symptom baseline

**Status:** Research scaffold; not approved for patient-facing use.

## Model identity

- Model family: TF-IDF word/character n-grams + Logistic Regression
- Training entry point: `ml/text_model/train.py`
- Artifact format: local Joblib file
- Intended role: baseline experiment for comparing text classification approaches

## Intended use

This baseline is for controlled academic experimentation on a reviewed, de-identified dataset.
It is not a diagnostic device, triage tool, or substitute for a clinician.

## Dataset

- Dataset name/version: **Not selected**
- Source/license: **Not reviewed**
- Retrieval date: **Not applicable**
- Patient/source grouping: **Not established**
- Duplicate normalized descriptions are grouped into one partition when no source group is supplied; this does not replace patient/source grouping.
- Label review: **Pending**

Training must not begin on real health data until the dataset intake checklist is completed.

## Evaluation

No model has been trained and no performance metrics are available yet. Do not insert assumed or
illustrative accuracy values here. Report macro-F1, balanced accuracy, per-class precision/recall,
confusion matrix, class support, confidence calibration and relevant subgroup performance after
a leakage-aware evaluation.

## Known limitations

- Performance depends on dataset label quality and representativeness.
- Free-text symptoms may be ambiguous, incomplete, misspelled, or expressed in different languages.
- A predicted class is not a confirmed disease.
- The current baseline does not provide clinically validated uncertainty or abstention thresholds.
- No prospective, external, or clinical validation has been performed.
- The model is not integrated into the public API.

## Risk controls required before integration

- Approved dataset provenance, license and privacy review
- Patient/source-level leakage-resistant evaluation
- Clinician-reviewed label taxonomy and error analysis
- Calibration and an explicit abstention/unsupported-input strategy
- Evaluation of false negatives and relevant demographic subgroups
- Model versioning, reproducible training and rollback plan
- Security and privacy review of input retention and logs
- Clear user-facing limitations and clinician escalation guidance

## Approval

- Dataset reviewer: Pending
- Clinical/domain reviewer: Pending
- ML evaluation reviewer: Pending
- API integration approval: Not granted
