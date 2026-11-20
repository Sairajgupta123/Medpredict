# Text symptom dataset candidate assessment

**Assessment date:** 20 November 2026  
**Decision:** No dataset is approved for training or patient-facing use yet.

This is a desk review of published dataset descriptions and papers. The underlying files have not
been downloaded or independently profiled in this repository. Reported sizes below are source-
reported metadata, not verified measurements from our own ingestion.

## Candidate comparison

| Candidate | Published description | Strength | Important risk | Current decision |
|---|---|---|---|---|
| Symptom2Disease (Kaggle source; mirrored on Hugging Face) | 1,200 natural-language descriptions, 24 labels, 50 examples per label | Closest match to the free-text input task | Small and artificially balanced; source provenance and original license need direct confirmation; no patient-level grouping described | Candidate for a small NLP prototype only after source/license review |
| Disease and symptoms dataset 2023 (Mendeley Data) | About 246,000 artificially generated rows, 773 diseases, 377 symptoms; CC BY 4.0 | Larger structured symptom/condition coverage and explicit license metadata | Artificial generation; source description says symptom/disease occurrence probabilities and severity were preserved, not clinical patient encounters; may not be natural-language free text | Candidate for structured symptom-set experiments, not the sole text model dataset |
| Consolidated Diseases_Dataset (Hugging Face) | Multiple source splits, including 246,945-row dhivyeshrk split and 1,200-row Symptom2Disease split; Apache-2.0 metadata | Convenient research index with source-specific splits | Aggregates multiple upstream datasets; top-level license metadata does not prove every upstream source has compatible rights; cross-split duplicates and label harmonization risks | Do not merge splits until each upstream source/license and overlap is audited |
| Disease Symptom Prediction (Kaggle / kaushil268) | Structured symptom-indicator rows with prognosis labels; widely reused in demos | Useful as a structured multi-label/binary symptom baseline | Frequently reused copies; exact duplicate rows and leakage can inflate metrics; Kaggle terms and original source must be checked | Secondary candidate only; inspect raw source and license before use |

## Primary references

1. Stark, Bran (2025), *Disease and symptoms dataset 2023*, Mendeley Data V1,
   DOI: https://doi.org/10.17632/2cxccsxydc.1  
   Dataset landing page: https://data.mendeley.com/datasets/2cxccsxydc/1  
   The landing page describes about 246,000 artificially generated rows, 773 diseases, 377 symptoms,
   and CC BY 4.0. The synthetic nature means it cannot establish real-world clinical performance.

2. Hassan, Abd El-Hafeez and Shams (2024), *Optimizing classification of diseases through language
   model analysis of symptoms*, Scientific Reports 14, 1507:
   https://doi.org/10.1038/s41598-024-51615-5  
   The paper describes Symptom2Disease as 1,200 samples across 24 diseases. It is useful as a
   published reference for the task, not proof that the dataset is representative of patients.

3. Symptom2Disease source page:
   https://www.kaggle.com/datasets/niyarrbarman/symptom2disease  
   Original source terms and license must be inspected directly before downloading or redistributing.

4. Hugging Face consolidated index:
   https://huggingface.co/datasets/kamruzzaman-asif/Diseases_Dataset  
   Its dataset card lists several upstream splits and Apache-2.0 metadata. Treat this as an index/
   mirror, not blanket proof that every upstream dataset can be used under one license.

5. Kaggle structured dataset:
   https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning  
   Verify the current source license and terms on Kaggle before use. A third-party repository or
   notebook license does not replace the underlying dataset license.

### Additional data-quality warning: 4,920-row structured dataset

The commonly reused 4,920-row, 41-class symptom-indicator dataset needs a duplicate audit before
any split. A recent independent repository analysis reports that its 4,920 raw rows reduce to
304 unique records after deduplication (93.8% exact duplicates). This is a secondary analysis,
not an independently reproduced result in MediPredict, but it is a strong reason to inspect the
original file and avoid trusting headline accuracy from random row splits.

Reference analysis: https://github.com/byron-ferrer/symptom-disease-comorbidity-mining

## Recommended staged approach

### Stage A — small natural-language prototype

After verifying the original Symptom2Disease source terms, use it only to test the ingestion,
preprocessing and baseline pipeline. Preserve the source's original train/test protocol if available,
and do not describe its scores as clinical accuracy. With only 50 examples per class, any held-out
estimate will have substantial uncertainty.

### Stage B — structured symptom benchmark

Independently review the Mendeley CC BY 4.0 dataset. Profile class counts, symptom-set duplicates,
single-symptom examples, class coverage, and whether generated samples share templates or rules.
Keep it as a separate benchmark; do not silently merge it with the natural-language corpus.

### Stage C — external validity

Before any patient-facing feature is considered, obtain a suitably governed, independently sourced,
clinically reviewed dataset with a defensible patient/source-level split and relevant population
coverage. Public synthetic or crowdsourced benchmark results are not a substitute.

## Acceptance gate before training

- [ ] Original source page and exact version archived in project documentation
- [ ] License and terms checked for download, modification, model training, and redistribution
- [ ] Dataset provenance and generation/collection method documented
- [ ] Raw schema and intended record grain confirmed
- [ ] Duplicate and near-duplicate analysis completed
- [ ] Label taxonomy and class counts reviewed
- [ ] Patient/source group key availability established; no invented group IDs
- [ ] Leakage-safe split protocol approved
- [ ] No direct identifiers or sensitive free text committed to Git
- [ ] Domain reviewer signs off on label interpretation and intended use

## Important distinction

A dataset can be legally reusable and still be unsuitable for clinical inference. Dataset license,
statistical quality, clinical validity, and product safety are four separate checks.
