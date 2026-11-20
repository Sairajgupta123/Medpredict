# MediPredict Backend

FastAPI service foundation for the MediPredict project.

## Requirements

- Python 3.11 or newer
- PostgreSQL 15 or newer for the application database
- pip

## Setup

Run these commands from the `backend/` directory.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item ..\.env.example .env
uvicorn app.main:app --reload
```

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp ../.env.example .env
uvicorn app.main:app --reload
```

Before using database-backed endpoints, create a PostgreSQL database and user matching
the `DATABASE_URL` in `.env`, or update that URL to match your local PostgreSQL setup.
The liveness endpoint does not require a live database connection. The readiness endpoint checks PostgreSQL connectivity.

The API is available at:

- API root: http://127.0.0.1:8000/
- Liveness check: http://127.0.0.1:8000/api/v1/health
- Database readiness: http://127.0.0.1:8000/api/v1/health/ready
- Interactive Swagger documentation: http://127.0.0.1:8000/docs

## Run tests

From the `backend/` directory:

```bash
pytest
```

## Authentication foundation

See [`../docs/architecture/authentication.md`](../docs/architecture/authentication.md) for the flow, token claims, and security limitations.

The API currently provides:
- `POST /api/v1/auth/register` — register with email and password; returns a short-lived bearer token.
- `POST /api/v1/auth/login` — authenticate using JSON email/password credentials.
- `GET /api/v1/auth/me` — return the current account profile; requires an Authorization bearer token.
- `PATCH /api/v1/auth/me` — update or clear the authenticated user's display name.

Passwords are hashed using Argon2. Access tokens are signed JWTs with an issuer, token type,
issued-at timestamp, and expiration. The access-token lifetime is configurable through
`ACCESS_TOKEN_EXPIRE_MINUTES` (default 30 minutes). Production startup rejects the built-in
development secret and requires a secret of at least 32 characters.

Email verification, password reset, refresh tokens, token revocation, account deletion, rate limiting,
and multi-factor authentication are not implemented yet. Logout on a stateless access token is not
represented as a fake server-side action; revocation/refresh-token design is a separate security step.

## Medical catalog API

Read-only endpoints:
- `GET /api/v1/catalog/symptoms?q=fever&limit=25&offset=0`
- `GET /api/v1/catalog/diseases?q=condition&limit=25&offset=0`

Both database-backed catalog endpoints expose only active records with
`review_status=approved` and complete reviewer audit metadata. Draft, in-review, retired and
inactive diseases and symptoms are excluded. Existing disease rows are migrated as drafts and
must be explicitly reviewed before publication. Database constraints reject approved disease
records without both a reviewer identifier and review timestamp.

Both endpoints support case-insensitive name/code search and bounded pagination (1–100 records).
They return an empty list until eligible database catalog entries have been added. These endpoints
do not perform symptom interpretation or return disease predictions.

The disease-to-symptom association endpoint is:

- `GET /api/v1/catalog/diseases/{disease_code}/symptoms?limit=50`

It returns only links that are explicitly approved with reviewer audit metadata, where both the
disease and symptom are active, approved, and have reviewer audit metadata. Existing links are
migrated as drafts. A relationship row alone never makes a symptom eligible for a disease.
This endpoint is catalog metadata only; it does not calculate disease likelihood or make a diagnosis.

### Catalog review authorization

Catalog review writes are restricted to accounts whose server-side `users.role` is
`reviewer` or `admin`. Public registration does not accept a role field; every new and
existing account defaults to `patient`. The role constraint permits only `patient`,
`reviewer`, and `admin`.

Authorized review actions:

- `PATCH /api/v1/catalog/review/diseases/{disease_code}`
- `PATCH /api/v1/catalog/review/symptoms/{symptom_code}`
- `PATCH /api/v1/catalog/review/diseases/{disease_code}/symptoms/{symptom_code}`

The request body contains one `status`: `draft`, `in_review`, `approved`, or
`retired`. The API derives `reviewed_by` from the authenticated reviewer identity and
sets `reviewed_at` on approval; clients cannot supply or impersonate these audit fields.
Moving an item out of approved state clears its current approval metadata.

Every review action must include a reason of 8–1,000 characters. The decision and its
audit event are committed in the same database transaction. Each event records target type,
target key, previous status, new status, reason, authenticated reviewer ID, and server timestamp.
The history is append-only through the API; there are no update or delete endpoints.

Authorized reviewers can inspect the latest history:

- `GET /api/v1/catalog/review/history?target_type=disease&target_key=DIS_CODE&limit=50`

Filters are optional; `limit` is bounded to 1–100. Patients cannot access the review history.
The audit record is operational traceability, not proof of clinical validity or reviewer credentials.

There is intentionally no public endpoint to grant reviewer/admin roles. Reviewer
access can be provisioned or revoked with the backend operational CLI after applying migrations.
Run from `backend/` using a trusted operations shell:

PowerShell:
```powershell
$env:MEDIPREDICT_ROLE_PROVISIONING_OPERATOR = "operator identity from your approved operations process"
python -m scripts.provision_catalog_reviewer --email reviewer@example.org --role reviewer --reason "Verified reviewer appointment and scope"
```

macOS/Linux:
```bash
export MEDIPREDICT_ROLE_PROVISIONING_OPERATOR="operator identity from your approved operations process"
python -m scripts.provision_catalog_reviewer --email reviewer@example.org --role reviewer --reason "Verified reviewer appointment and scope"
```

The command requires an existing active account, verified email for reviewer grants, a reason,
and exact-email interactive confirmation. Use `--role patient` to revoke reviewer access and
`--dry-run` to validate a proposed change without committing it. The command records the
previous/new role, target account, operator identity, reason, and server timestamp in the
append-only `role_provisioning_events` table in the same transaction as the role update.
The operator identity is asserted by the trusted shell environment; it is not independently
authenticated by the application. Restrict database credentials and shell access to authorized
operations personnel, and preserve database backups and audit records.

This CLI deliberately cannot grant, revoke, or modify the `admin` role. Admin bootstrap or
changes require a separate DBA-controlled process outside the application. Do not promote accounts through ad-hoc
SQL in a production database. Reviewer role assignment alone does not establish clinical
qualification; the organization must verify credentials and scope before granting it.

## Database foundation

- SQLAlchemy 2.x declarative base: `app.db.base.Base`
- PostgreSQL engine: `app.db.session.engine`
- Request-scoped session dependency: `app.db.session.get_db`
- Database URL is loaded from the `DATABASE_URL` environment variable.
- Initial ORM models are registered in `app.models` for users, diseases, symptoms, predictions, skin-image metadata, ranked results, and feedback.
- The schema overview and privacy/safety decisions are documented in [`../docs/architecture/database-schema.md`](../docs/architecture/database-schema.md).
- Alembic is configured in `alembic.ini` and `alembic/env.py`.

The engine uses `pool_pre_ping` and does not establish a network connection merely by being imported.
Each API request that uses `get_db` receives its own session, which is closed after the request.

### Apply database migrations

After PostgreSQL is installed, the database and credentials in `.env` are configured, and you have
confirmed that the target database is the intended development database, run from `backend/`:

```bash
alembic upgrade head
```

To inspect the current migration revision:

```bash
alembic current
```

Do not run migrations against a production database from a development workstation. Review every
future migration before applying it, and take backups before production schema changes.

The liveness endpoint `/api/v1/health` only reports that the API process responds. The readiness
endpoint `/api/v1/health/ready` executes `SELECT 1` and returns HTTP 503 if the database is unavailable.

## Profile management

Only the signed-in user's display name is currently editable. Email changes, password changes, account deletion, and verified-email flows require additional security workflows and are not exposed as profile fields.

## Current scope and safety

The migrations are committed but have not been applied to a live PostgreSQL database in this workspace.
No patient data is being stored, and email verification, password reset, refresh-token rotation,
token revocation, and disease prediction are not implemented.
Do not place real patient data in development or test databases. Production secrets and database
credentials must be stored in the deployment environment, never committed to Git.

## Symptom phrase normalization API

The symptom-input milestone is deliberately non-diagnostic:

- `GET /api/v1/symptoms/catalog` returns the versioned research vocabulary's stable IDs, labels and categories. Phrase aliases are intentionally not exposed.
- `POST /api/v1/symptoms/normalize` accepts a text description up to 4,000 characters and a required self-reported context object.
- Context values are constrained to duration (`less_than_24_hours`, `one_to_three_days`, `four_to_seven_days`, `more_than_one_week`, `not_sure`), severity (`mild`, `moderate`, `severe`, `not_sure`) and onset (`sudden`, `gradual`, `comes_and_goes`, `not_sure`).
- A versioned research vocabulary maps explicit phrases to canonical symptom identifiers.
- Negated, historical and uncertain mentions are returned separately for manual review.
- Unrecognized wording is not echoed in the response.
- The request is processed in memory by this endpoint and is not written to prediction history.
- The response returns the supplied context unchanged and declares `clinical_interpretation_performed: false`, `model_inference_performed: false`, `disease_prediction_performed: false`, and `research_only: true`.
- These response flags are an API contract: this endpoint performs curated phrase matching only. It does not load or call either ML research pipeline, calculate disease probabilities, rank conditions, or make a diagnosis.

The context fields are user descriptions only. They are not verified measurements, clinical severity scores or triage signals. The normalizer is a conservative phrase matcher, not a clinically validated NLP model. It does not reliably resolve all negation, timeline, severity, uncertainty or conversational context. Do not use it to infer diseases, rank conditions, triage patients or recommend treatment. The vocabulary is research scaffolding and needs clinical review before broader use.

The taxonomy is packaged at `app/data/symptom_taxonomy.json` and included in built distributions through setuptools package data. The original research vocabulary and tests remain in the repository-level `ml/` directory.

## Reviewed medical knowledge API

The public knowledge endpoint returns general-care information only when all publication gates pass:
- The recommendation is marked active and approved, with a non-empty reviewer ID and review timestamp.
- Its validity window includes the current date and its `next_review_due` date is not overdue (a null due date means no scheduled date has been recorded).
- At least one linked medical reference is approved, has its own reviewer ID and review timestamp, and is not past its `next_review_due` date.
- The response includes the scheduled review due dates alongside source provenance; overdue sources and recommendations are withheld automatically until reviewed again.
- The requested locale matches the recommendation locale.
- Database check constraints prevent approved records without review audit metadata and invalid validity windows.

Endpoint:

```http
GET /api/v1/knowledge/diseases/{disease_code}/recommendations?locale=en&category=general_care
```

Supported categories are `general_care`, `precautions`, `lifestyle`, `diet`,
`when_to_seek_care`, and `emergency_signs`. Supported urgency labels are `routine`, `prompt`,
`urgent`, and `emergency`.

Knowledge records default to draft/unpublished. There is intentionally no public write endpoint or
seeded medical advice. A qualified reviewer must verify the source, wording, applicability, locale,
validity period and approval metadata before content can be published. This initial module does not
store medication instructions or dosage advice.

The endpoint also requires the disease catalog entry itself to be active, explicitly approved,
and backed by reviewer audit metadata. Draft, in-review, retired or unaudited disease entries
cannot be used to retrieve public guidance.

The endpoint is a source-backed education layer, not a diagnosis or treatment plan. Emergency
information must be carefully reviewed and localized before any production use.
