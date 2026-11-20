# MediPredict ML workspace

This workspace contains modality-specific experiments. The text and skin-image models are
independent; their scores must never be presented as a combined or clinically validated diagnosis.

## Text baseline (research only)

The first baseline uses:
- TF-IDF word and character n-grams
- Logistic Regression with balanced class weights
- A held-out evaluation split
- Macro-F1, balanced accuracy, per-class precision/recall/F1 and a confusion matrix

### Dataset contract

Training expects a reviewed CSV with:
- `symptom_text`: user-like symptom description, not an identifier
- `condition_label`: normalized target class
- `group_id` (strongly recommended/required for final evaluation): patient, source case, or original record group used to prevent near-duplicate leakage

Do not commit raw health datasets, patient information, identifiable records, trained models, or generated artifacts.
Raw and processed dataset directories and model artifact directories are ignored by Git.

### Run locally

From the repository root:

```bash
python -m pip install -r ml/requirements.txt
python -m ml.text_model.train --data ml/datasets/curated/text_symptoms.csv
```

The training command writes a research artifact and a metrics JSON under `ml/artifacts/text_baseline/`.
These outputs are local and ignored by Git. Never load a model artifact from an untrusted source.

### Evaluation safeguards

- Prefer patient/source-grouped splits. The script uses `group_id` when present.
- If no group identifier exists, a stratified row split is used only as a provisional exploration;
  the resulting score is not a reliable estimate when duplicate/patient leakage is possible.
- Rare classes with too few examples are a dataset readiness issue, not a reason to silently drop
  them from evaluation.
- Report macro-F1 and per-class recall; accuracy alone is inadequate for imbalanced medical labels.
- Review confusion pairs and false negatives with a qualified domain reviewer.
- A high model score does not establish clinical validity or readiness for patient use.

The baseline is not wired into the public prediction API. API integration requires a separately
reviewed model card, validation protocol, uncertainty/abstention behavior, privacy review and
explicit approval.

## Symptom normalization (initial vocabulary)

A conservative English phrase matcher is available in `ml/symptom_normalizer.py`.
It maps explicitly curated phrases to versioned symptom IDs from
`ml/symptom_taxonomy.json`.

Example:

```python
from ml.symptom_normalizer import normalize_symptoms

result = normalize_symptoms("My head hurts and I have a cough.")
print(result["matched_symptoms"])
```

The matcher flags a few obvious nearby negation, historical and uncertainty cues for review.
It cannot reliably understand clinical context, negation, timing, severity, multilingual text,
or emergencies. Every result requires review. It does not diagnose or perform triage and is
not yet connected to the backend API or model training pipeline.

See `ml/SYMPTOM_NORMALIZATION.md` for its scope and limitations.

## Skin-image research

See `ml/datasets/skin_image_assessment.md` for the HAM10000 versus PAD-UFES-20 modality and
provenance assessment, and `ml/model_cards/skin_image_baseline.md` for the required validation
gates. No skin-image dataset has been approved or model trained.

A manifest audit utility is available at `ml/datasets/audit_skin_manifest.py`. It checks aggregate
metadata, patient/lesion grouping counts, safe relative paths, image decoding and exact duplicate
image content without printing raw identifiers or file paths. See `ml/datasets/README.md` for
the expected CSV columns and command. This is not a clinical validation tool.
