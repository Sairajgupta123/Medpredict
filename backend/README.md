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

## Database foundation

- SQLAlchemy 2.x declarative base: `app.db.base.Base`
- PostgreSQL engine: `app.db.session.engine`
- Request-scoped session dependency: `app.db.session.get_db`
- Database URL is loaded from the `DATABASE_URL` environment variable.
- Initial ORM models are registered in `app.models` for users, diseases, symptoms, predictions, skin-image metadata, ranked results, and feedback.
- The schema overview and privacy/safety decisions are documented in `../docs/architecture/database-schema.md`.
- Alembic is configured in `alembic.ini` and `alembic/env.py`; the checked-in baseline is `alembic/versions/0001_initial_schema.py`.

The engine uses `pool_pre_ping` and does not establish a network connection merely by being imported.
Each API request that uses `get_db` receives its own session, which is closed after the request.

### Apply the initial migration

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

The initial migration file is committed but has not been applied to a live PostgreSQL database in this workspace. No patient data is being stored, and email verification, password reset, refresh-token rotation, token revocation, and disease prediction are not implemented.
Do not place real patient data in development or test databases. Production secrets and database
credentials must be stored in the deployment environment, never committed to Git.
