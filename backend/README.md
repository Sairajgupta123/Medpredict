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
The current health endpoint does not require a live database connection.

The API is available at:

- API root: http://127.0.0.1:8000/
- Health check: http://127.0.0.1:8000/api/v1/health
- Interactive Swagger documentation: http://127.0.0.1:8000/docs

## Run tests

From the `backend/` directory:

```bash
pytest
```

## Authentication foundation

The API currently provides:
- `POST /api/v1/auth/register` — register with email and password; returns a short-lived bearer token.
- `POST /api/v1/auth/login` — authenticate using JSON email/password credentials.
- `GET /api/v1/auth/me` — return the current account profile; requires an Authorization bearer token.

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
- Alembic is configured in `alembic.ini` and `alembic/env.py`; the first reviewed migration still needs to be generated and applied against a configured PostgreSQL database.

The engine uses `pool_pre_ping` and does not establish a network connection merely by being imported.
Each API request that uses `get_db` receives its own session, which is closed after the request.

## Current scope and safety

This milestone adds an initial ORM schema draft only. No migration has been applied, no patient data
is being stored, and email verification, password reset, refresh-token rotation, token revocation, and disease prediction are not implemented.
Do not place real patient data in development or test databases. Production secrets and database
credentials must be stored in the deployment environment, never committed to Git.
