# Symptom normalization

This is a conservative phrase-matching utility, not a clinical NLP system.

## Scope

- Maps only explicitly curated English phrases to stable symptom identifiers.
- Applies Unicode compatibility normalization, case folding and punctuation normalization.
- Uses token-boundary matching and prefers longer phrases when aliases overlap.
- Does not infer diseases or missing symptoms, reliably resolve negation/history/uncertainty, assess severity, or provide triage. A few obvious nearby negation, historical and uncertainty cues are flagged for review, but this is not comprehensive language understanding.
- Returns no raw user text or unmatched phrase content.
- Marks every result as requiring review.

## Example

```python
from ml.symptom_normalizer import normalize_symptoms

result = normalize_symptoms("My head hurts and I feel like vomiting.")
```

## Taxonomy governance

The initial vocabulary is an engineering seed only. It is not a validated medical terminology
standard and has not been reviewed by a clinician. Before expanding or using it in patient-facing
workflows, obtain clinical review, document language and regional coverage, define synonyms and
ambiguous terms, and add versioned regression tests.

## Safety boundary

Phrase matches are not confirmed current symptoms: the utility cannot reliably detect all negation
("no fever"), uncertainty ("maybe a fever"), history ("I had fever last week"), or quoted text.
It must not be used alone to drive diagnosis, treatment, triage, or emergency decisions.

## Taxonomy structure validation

The loader now requires semantic version metadata (`taxonomy_version`), a non-empty governance
status, language, normalization policy, and a non-empty symptom list. Every symptom must have a
non-empty ID, label and category plus a list of non-empty aliases. Duplicate IDs and normalized
alias collisions across different symptom IDs are rejected. Normalization results report the
loaded taxonomy version so downstream records can identify the vocabulary revision used.

These checks establish structural consistency only. They do not establish clinical correctness,
terminology-standard conformance, completeness, or approval. Taxonomy changes still require
documented human review and regression tests.
