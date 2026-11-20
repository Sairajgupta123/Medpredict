# Dataset intake and governance

No health dataset is bundled with this repository. Do not download or commit patient-level data
until its source, license, permitted use, privacy constraints and suitability have been reviewed.

## Candidate comparison

The current research shortlist and the limitations of each candidate are documented in
[`candidate_assessment.md`](candidate_assessment.md). A source that is useful for an educational
baseline is not automatically suitable for patient-facing predictions.

## Intake checklist

Before accepting a dataset, record:
- Dataset name, source URL and retrieval date
- Version/release identifier and license
- Intended research use and any restrictions
- Whether records are patient-level, encounter-level, synthetic, or aggregated
- Available patient/source grouping identifier and whether it can be used safely
- Class definitions, label provenance and known label quality limitations
- Number of rows and unique groups per class
- Missingness, duplicate records and conflicting labels
- Demographic/geographic coverage and known sampling bias
- Whether a qualified reviewer has approved the label mapping

## Text model CSV contract

The exploratory text baseline expects a CSV with:

| Column | Required | Description |
|---|---|---|
| `symptom_text` | Yes | De-identified symptom description |
| `condition_label` | Yes | Reviewed normalized target label |
| `group_id` | Strongly recommended; required for final evaluation | Non-identifying patient/source grouping key |

Never place names, phone numbers, addresses, email addresses, medical record numbers, or other
direct identifiers in `symptom_text` or `group_id`. A pseudonymous group key is still sensitive
and must not be committed or logged. Keep datasets outside version control in approved, access-
controlled storage.

## Run the local audit

Install `ml/requirements.txt`, then run from the repository root:

```bash
python -m ml.datasets.audit_csv --data path/to/reviewed_dataset.csv
```

The audit reports schema, row counts, missingness, exact and normalized duplicate rates, label
distribution, group counts, and text-length summaries. It does not print symptom text or group IDs.
The tool does not establish dataset provenance, licensing, clinical validity, or absence of privacy
risks; those require separate review.

## Evaluation readiness

A row-level random split is only a provisional experiment. It cannot rule out patient overlap,
duplicate encounters, or source-specific leakage. Final evaluation requires a defensible group-aware
split, sufficient independent groups per class, and documented class coverage in both partitions.

A public dataset license does not automatically establish clinical validity or permission for
deployment. Record dataset limitations and intended-use restrictions in the model card.

## Skin-image manifest contract

The exploratory skin-image audit expects a CSV manifest with:

| Column | Required | Description |
|---|---|---|
| `image_id` | Yes | Non-identifying image key |
| `image_path` | Yes | Path relative to the image root |
| `label` | Yes | Dataset-provided class label |
| `patient_id` | Recommended | Pseudonymous patient grouping key |
| `lesion_id` | Recommended | Pseudonymous lesion grouping key |

Run the aggregate audit from the repository root:

```bash
python -m ml.datasets.audit_skin_manifest --manifest path/to/manifest.csv --image-root path/to/images
```

The audit checks missing/duplicate manifest values, patient/lesion group counts, path traversal,
missing files, image decoding, supported formats and exact duplicate image content. It adds an
aggregate `training_readiness` section that blocks reviewer sign-off when patient grouping is
missing, any class has fewer than three distinct patients, files are invalid, or exact duplicate
image content is present. Its JSON output excludes raw image paths and group identifiers. A passing
technical audit is not automatic training approval and does not verify source authenticity, license,
diagnostic labels, skin-tone coverage or clinical suitability. Keep the manifest and all images in approved
local/private storage; do not commit them to Git.

## Symptom-text intake audit

Run the aggregate-only CSV audit before considering a symptom dataset:

```bash
python -m ml.datasets.audit_csv --data path/to/reviewed_symptoms.csv --output audit.json
```

The report never echoes raw symptom text, group identifiers or detected contact values. Its
`training_readiness` section checks required columns, nonblank values, patient/source grouping,
minimum distinct groups per class, group-label consistency, conflicting normalized descriptions
and obvious email/phone patterns. A passing technical check only means the dataset can proceed to
human review. It does not approve licensing, de-identification, clinical labels or model training.

The email/phone patterns are intentionally simple and can miss identifiers or flag benign text.
Do not upload or commit identifiable health information. Keep raw and processed datasets in
approved private storage.