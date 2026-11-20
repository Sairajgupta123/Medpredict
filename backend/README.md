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

The database-backed symptom endpoint exposes only active records with
`review_status=approved` and complete reviewer audit metadata. Draft, in-review, retired and
inactive terms are excluded. The disease catalog currently filters active records; disease-specific
clinical review governance is a separate pending milestone.

Both endpoints support case-insensitive name/code search and bounded pagination (1–100 records).
They return an empty list until eligible database catalog entries have been added. These endpoints
do not perform symptom interpretation or return disease predictions.

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
- The response returns the supplied context unchanged and declares `clinical_interpretation_performed: false`.

The context fields are user descriptions only. They are not verified measurements, clinical severity scores or triage signals. The normalizer is a conservative phrase matcher, not a clinically validated NLP model. It does not reliably resolve all negation, timeline, severity, uncertainty or conversational context. Do not use it to infer diseases, rank conditions, triage patients or recommend treatment. The vocabulary is research scaffolding and needs clinical review before broader use.

The taxonomy is packaged at `app/data/symptom_taxonomy.json` and included in built distributions through setuptools package data. The original research vocabulary and tests remain in the repository-level `ml/` directory.

## Reviewed medical knowledge API

The public knowledge endpoint returns general-care information only when all publication gates pass:
- The recommendation is marked active and approved, with a non-empty reviewer ID and review timestamp.
- Its validity window includes the current date.
- At least one linked medical reference is approved and has its own reviewer ID and review timestamp.
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

The endpoint is a source-backed education layer, not a diagnosis or treatment plan. Emergency
information must be carefully reviewed and localized before any production use.
