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
