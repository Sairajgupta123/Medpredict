# MediPredict

**AI-Powered Disease Prediction and Healthcare Assistance System**

MediPredict is an academic major project exploring two complementary AI-assisted analysis workflows in one web application:

1. **Text-based symptom analysis** — users enter symptoms in text or through a guided symptom interface. A machine-learning pipeline estimates possible conditions from a defined and evaluated dataset.
2. **Skin-image analysis** — users upload a skin image for classification among explicitly supported dataset classes using a separately trained and evaluated image model.

Both workflows connect to a shared, curated health-information and care-guidance layer. The application is intended as an educational decision-support prototype, not a substitute for a qualified healthcare professional or a clinical diagnosis.

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

The repository foundation, FastAPI backend, SQLAlchemy schema, initial Alembic migration, authentication endpoints, profile management, read-only medical catalog APIs, and a research-only text classification baseline have been added on `develop`.

The text baseline includes dataset validation, group-aware splitting when a grouping key is available, and imbalance-aware evaluation outputs. It is not connected to the public prediction API and has not been trained on an approved dataset. No clinical performance claims are made.

An initial English symptom phrase-normalization vocabulary and conservative matcher have also been added. It flags a limited set of obvious negation, historical and uncertainty contexts for review; it is not a clinically validated NLP system and is not connected to the prediction API. Skin-image work now includes dataset assessment, manifest auditing, patient-grouped splits, preprocessing, a MobileNetV3 factory, training-only class weighting, per-class sensitivity/specificity metrics, an offline training runner, heuristic image-quality screening, confidence-based abstention, calibration helpers and a safety-gated research inference helper. No skin dataset has been approved and no model has been trained or evaluated. Reviewed dataset ingestion, recommendation content, clinician-reviewed safety rules, and frontend workflows remain under development. Features listed above are planned scope unless explicitly identified as implemented.

## Safety notice

MediPredict is an academic prototype. Its outputs must not be used to self-diagnose, delay urgent care, or start, stop, or change treatment. Skin-image classification is limited to the classes and image conditions supported by the validated model. If symptoms are severe or urgent, seek immediate professional medical care.
