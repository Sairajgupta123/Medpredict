# Prediction and symptom-review pipeline

## Current implementation status

MediPredict currently exposes a limited symptom phrase recognizer and an approved-catalog overlap comparison. Neither is a clinical prediction model.

### Text symptom flow

1. The browser sends symptom text and self-reported duration, severity and onset to the same-origin Next.js route.
2. The route validates the request and forwards it to `POST /api/v1/symptoms/normalize`.
3. The backend matches a curated phrase taxonomy in memory. It does not persist the submitted narrative.
4. Negated, historical and uncertain mentions are separated for human review. Unsupported residual wording is flagged.
5. The UI asks the user to confirm each recognized item. A phrase match is not treated as proof that a symptom is present.

### Approved catalog comparison

After the user explicitly confirms one or more symptoms as present:

1. The frontend sends only those symptom identifiers to `POST /api/symptoms/catalog-match`.
2. The same-origin Next.js route validates the list (1–20 unique identifiers) and proxies the request.
3. The backend verifies that each selected symptom is active and approved, with reviewer identity and review timestamp.
4. Disease entries, symptom entries and disease-symptom associations are all filtered to active, approved records with reviewer audit metadata.
5. Results show matched association counts and a catalog-overlap ratio. The ratio is only a description of catalog coverage for that disease entry.

The static phrase taxonomy used by the text recognizer and the database-backed, reviewer-governed disease catalog are separate data sources. A phrase-taxonomy identifier is eligible for matching only after a corresponding database symptom record and its disease associations have been created and approved with the required audit metadata. Until then, the endpoint rejects that identifier as not present in the approved catalog; this is an expected governance boundary, not evidence that the symptom is medically irrelevant.

The overlap ratio is **not** a disease probability, clinical risk score, confidence estimate, or measure of diagnostic accuracy. The matcher does not use the association relevance weight to imply calibrated risk. Diseases without an approved matched association are not returned. An empty result does not rule out disease.

### Privacy boundaries

- Free-text symptom narratives are sent only to the normalization endpoint and are not stored by that endpoint.
- The catalog comparison receives only confirmed symptom IDs, not the original narrative or the self-reported context fields.
- The comparison request is not stored as prediction history.
- Do not add request-body logging or analytics that capture symptom narratives.

### Clinical and governance constraints

- Draft, in-review, retired and inactive catalog records must never be exposed as matches.
- An approved status alone is insufficient: reviewer identity and review timestamp are required.
- This prototype must not claim diagnosis, disease probability, model accuracy, treatment guidance or clinical validation.
- Severe, rapidly worsening or worrying symptoms require professional assessment; the prototype must never be used to decide whether care is necessary.

### Skin-image intake security foundation

The backend now contains a standalone validation utility at `backend/app/services/skin_image_validation.py`. It checks actual decoded image format rather than trusting filenames, enforces an 8 MiB payload limit, a 6,000-pixel edge limit and a 20-megapixel limit, rejects animated/multi-frame files, and re-encodes accepted JPEG, PNG and WebP images from raw pixels to remove EXIF, ICC and textual metadata. Pillow is a backend dependency for this processing.

An additional advisory quality helper reports basic capture indicators (small dimensions, very dark or overexposed pixels, and near-uniform/low-contrast images). These are technical warnings only; they are not a clinical quality score, do not establish that a lesion is visible, and must not be used to diagnose or deny care.\n\nThis utility is not an HTTP upload endpoint and does not store files. It is not yet connected to prediction history or model inference. Upload routes remain intentionally disabled until private object storage, authenticated upload controls, explicit image-processing consent, retention rules, deletion verification, request-size enforcement and operational rate limits are implemented. The utility does not establish that an image is clinically suitable or support a diagnosis.



### Private storage adapter boundary

`backend/app/services/skin_image_storage.py` defines a narrow private-storage protocol and a default adapter that fails closed. No cloud bucket, local disk fallback, public URL, or upload route is configured. Object keys are generated from server-side image UUIDs and safe extensions; they do not contain account identifiers or original filenames. A production adapter must provide private-only access, encryption at rest, TLS, least-privilege credentials, no public object URLs, and idempotent deletion. Retrieval must only be called after application-level ownership checks. The protocol is an integration contract, not proof that a storage provider has been configured or audited.

Before enabling image upload, the next implementation stages must add a separate image-processing consent purpose and immutable consent events, persist only metadata after successful private object creation, handle partial failures with compensating deletion, implement verified deletion before acknowledging revocation, and test cross-user access isolation. Retention expiry and operational deletion reconciliation are also required.

## Not implemented yet

- A clinically validated disease-risk model and its external validation evidence.
- A curated, source-cited and clinically reviewed disease/symptom knowledge base with adequate coverage.
- Model calibration, subgroup performance, bias evaluation and prospective evaluation.
- Skin-image classification, dataset provenance, image-quality checks, secure object storage and deletion lifecycle.
- Clinician-facing review workflows for prediction outputs.

These capabilities require suitable data, documented approvals, validation and privacy controls before any clinical-facing use.
