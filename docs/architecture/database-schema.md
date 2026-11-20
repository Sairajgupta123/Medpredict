# MediPredict initial database schema

**Status:** Initial ORM schema drafted on the `develop` branch. This document describes the
first persistence layer; it is not a clinical data standard or a claim of production readiness.

## Design goals

- Keep text and skin-image analysis independently usable.
- Keep each prediction request separate from its ranked candidate results.
- Allow guest predictions while supporting an optional registered account.
- Keep uploaded image bytes outside PostgreSQL; store only a private object-storage key and
  verification metadata in the database.
- Store symptom input text only when the user has explicitly consented to history storage.
  The API/service layer must enforce this rule; a database boolean alone is not consent.
- Preserve model version and disclaimer version so later reviews can identify the system version
  that produced a result.
- Treat prediction output as decision support, never as a confirmed diagnosis.

## Entity relationship overview

```mermaid
erDiagram
    USERS ||--o{ PREDICTIONS : owns
    PREDICTIONS ||--o{ PREDICTION_RESULTS : produces
    DISEASES ||--o{ PREDICTION_RESULTS : candidate
    PREDICTIONS ||--o| SKIN_IMAGE_ANALYSES : describes
    PREDICTIONS ||--o{ PREDICTION_FEEDBACK : receives
    DISEASES ||--o{ DISEASE_SYMPTOMS : maps
    SYMPTOMS ||--o{ DISEASE_SYMPTOMS : maps
    DISEASES ||--o{ CARE_RECOMMENDATIONS : contextualizes
    CARE_RECOMMENDATIONS ||--o{ RECOMMENDATION_REFERENCES : cites
    MEDICAL_REFERENCES ||--o{ RECOMMENDATION_REFERENCES : supports
```

## Tables in the first schema

| Table | Purpose | Important fields |
|---|---|---|
| `users` | Registered accounts | UUID, unique email, password hash, display name, timestamps |
| `diseases` | Curated supported-condition catalog | stable code, name, description, active flag |
| `symptoms` | Normalized symptom catalog | stable code, unique name, active flag, review status, reviewer and timestamp |
| `disease_symptoms` | Many-to-many catalog mapping | disease ID, symptom ID, relevance weight |
| `predictions` | One analysis request and lifecycle | optional user, modality, status, consent flag, model/disclaimer versions |
| `prediction_results` | Ranked candidate conditions | prediction, disease, rank, probability field, explanation |
| `skin_image_analyses` | Metadata for image analysis | private object key, MIME type, SHA-256, class, confidence, quality/review flags |
| `prediction_feedback` | Feedback about usefulness | prediction, helpful flag, comment, review status |
| `medical_references` | Versioned source provenance | publisher, URL, evidence type, version, review status, reviewer |
| `care_recommendations` | General-care information | disease, locale, category, urgency, version, approval and validity |
| `recommendation_references` | Recommendation-to-source links | recommendation ID, reference ID, reviewer note |

## Key rules

### Prediction lifecycle

- `modality` is restricted to `text`, `skin_image`, or `combined`.
- `status` is restricted to `pending`, `completed`, `failed`, or `review_required`.
- A guest request may have a null `user_id`; account deletion should not erase aggregate monitoring evidence by accident.
- `combined` is a storage capability only. It does not imply clinically validated multimodal fusion.
- Ranked result probabilities are constrained to the inclusive range 0–1. Their interpretation and calibration must be validated by the ML evaluation pipeline.

### Symptom catalog publication

- The packaged `/symptoms/catalog` taxonomy is research vocabulary and remains explicitly unvalidated.
- The database-backed `/catalog/symptoms` endpoint is a separate curated publication channel.
- A database symptom is public only when `is_active=true` and `review_status='approved'`.
- Approval requires both a non-empty reviewer identifier and a review timestamp; the database check constraint rejects incomplete approval metadata.
- Draft, in-review, retired and inactive symptoms are excluded from public search and pagination counts.
- No research taxonomy entries are automatically copied into the reviewed database catalog.
- A qualified reviewer must independently verify terminology, definition, scope and suitability before approving a record. This project does not currently provide a reviewer UI or claim that any symptom terms have received real clinical approval.

### Skin-image privacy and quality

- Image bytes must be stored in private object storage, never in a database binary column.
- `object_key` must not be a public URL. Access must be mediated by an authorized backend route or short-lived signed URL.
- Validate file size, MIME type, actual file signature, and image decodability before inference.
- Reject unsupported formats and poor-quality or out-of-scope images; mark uncertain cases for clinician review.
- Define retention and deletion behavior for both the object and its metadata before enabling uploads.

### Account security

- `password_hash` must contain a modern password hash (for example Argon2id), never a plaintext or reversible password.
- Authentication, email verification, rate limiting, and account recovery are separate application-layer work and are not implemented by these models.
- Do not log passwords, raw health text, image object keys, or secrets.

### Medical safety and governance

- Prediction candidates are not diagnoses and must be presented with uncertainty and a clear clinician-review message.
- No medication or dosage advice is stored or generated by these tables.
- Public care information is served only when the recommendation is active, approved, within its validity dates, and linked to at least one approved medical reference.
- Medical references retain publisher, URL, evidence type, version, access date and review status. Recommendation versions retain locale, category, urgency, reviewer and validity dates.
- Draft and in-review material is not exposed by the public knowledge endpoint. The endpoint returns general education only, not diagnosis or treatment plans.
- Feedback is a usefulness signal, not proof of a diagnosis or clinical outcome.

## Deliberately deferred tables

The initial ORM pass now includes medical references and care recommendations with provenance links.
Generated reports, chat sessions/messages, audit events, consent receipts, model registry/evaluation
runs, and admin roles remain deferred.
These need their own retention, access-control, provenance, and threat-model decisions before schema
implementation.

## ORM source

- `backend/app/models/user.py`
- `backend/app/models/catalog.py`
- `backend/app/models/prediction.py`
- `backend/app/models/feedback.py`
- `backend/app/models/knowledge.py`
- `backend/app/models/__init__.py`

Alembic migrations `0002_reviewed_medical_knowledge.py` and
`0003_reviewed_symptom_catalog.py` add provenance-aware knowledge tables and symptom approval
metadata after the initial schema. Migrations are committed but have not been applied to a live
PostgreSQL database.
