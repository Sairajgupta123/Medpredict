# Disease–symptom mapping registry

This is a provenance and structure scaffold, not a clinically validated disease ontology. The
initial registry intentionally contains no disease–symptom relationships. Do not invent or infer
clinical relationships to populate it.

## Registry record requirements

Each condition has a stable code, display label, definition, and governance status. Each relationship
must reference a known condition code and a stable symptom ID from `ml/symptom_taxonomy.json`.
A relationship also requires a constrained relation type, one or more evidence records with HTTPS
source URL, title and access date, status, and reviewer/date metadata when marked approved.

Supported relationship types are deliberately cautious: `associated_with`, `may_include`, and
`commonly_reported_with`. They do not express diagnostic criteria, causal relationships, likelihood,
severity, or treatment advice.

## Run the structural audit

From the repository root:

```bash
python -m ml.disease_mapping --registry ml/disease_mapping_registry.json
```

The report checks structure and references against the current symptom taxonomy. It always returns
`automatic_clinical_approval=false` and `patient_facing_use_permitted=false`, even when structure
passes. Human clinical review, source verification, dataset rights review and a separate product
safety approval are required before any relationship can be used.

Never put patient data, credentials, or restricted source documents in this registry or Git.
