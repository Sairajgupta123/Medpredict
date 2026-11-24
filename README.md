# MediPredict

**AI-Assisted Health Information and Assessment Prototype**

MediPredict is an academic major project exploring privacy-conscious health-information workflows in one web application:

1. **Text-based symptom input** — users can select supported symptom labels or submit a short description for conservative phrase matching. The current implementation does not estimate disease probability or provide a diagnosis.
2. **Skin-image intake and review** — users can submit images only through consent-gated private storage and technical capture-quality review. Skin-image disease classification is disabled because no dataset/model has completed the required approval and clinical validation.

The application is an educational research prototype, not a diagnostic service, triage tool, or substitute for a qualified healthcare professional.

## Project principles

- Evidence-led recommendations; no fabricated cures or unsupported medication/dosage advice.
- Clear model limitations and calibrated uncertainty; no unverified accuracy claims.
- Separate text and image models, datasets, evaluation and versioning.
- Privacy-conscious handling of account details and uploaded images.
- Human clinical review is required before any real-world clinical use.

## Planned architecture

- `frontend/` — responsive web application.
- `backend/` — API, authentication, validation and application services.
- `ml/` — symptom model, skin-image model, preprocessing and evaluation.
- `knowledge_base/` — curated condition, symptom, care-guidance and reference content.
- `database/` — schema, migrations and seed data.
- `docs/` — architecture, API, database, testing and project documentation.
- `deployment/` — container and deployment configuration.
- `scripts/` — development and maintenance utilities.

The exact framework versions and interfaces will be documented as implementation is added.

## Development workflow

- `main` is reserved for stable, reviewed project milestones.
- `develop` is the active integration branch.
- Feature work should be small, reviewable and tested before integration.

## Current status

The repository foundation, FastAPI backend, SQLAlchemy schema and migrations, authentication and account-management endpoints, read-only medical catalog APIs, consent-gated private skin-image intake/review controls, and a research-only text-model experimentation pipeline have been added on `develop`.

The text-model research pipeline includes dataset validation, group-aware train/validation/test splitting, class-aware evaluation, model comparison, validation-only model selection, calibration helpers and coverage-based abstention. No approved dataset has been used for training, the text model is not connected to the public symptom API, and no clinical performance claims are made.

An initial English symptom phrase-normalization vocabulary and conservative matcher have also been added. It flags a limited set of obvious negation, historical and uncertainty contexts for review; it is not clinically validated and is not a diagnostic NLP system. Skin-image research utilities include dataset assessment, manifest auditing, patient-grouped split helpers, preprocessing, model factories, evaluation metrics, experiment metadata, image-quality screening, abstention and calibration helpers. These are research utilities only: no skin dataset has been approved, no model has been trained or clinically evaluated, and production inference remains disabled. A limited set of symptom normalization and approved-catalog overlap endpoints is available for research display only. Recommendation content, clinician-reviewed safety rules and broader clinical workflows remain under development.

## Safety notice

MediPredict is an academic prototype. Its outputs must not be used to self-diagnose, delay urgent care, or start, stop, or change treatment. Symptom phrase matches and catalog overlap are not disease probabilities or risk scores. Skin-image disease classification is currently disabled; image review is restricted to technical capture quality. If symptoms are severe or urgent, seek immediate professional medical care.
