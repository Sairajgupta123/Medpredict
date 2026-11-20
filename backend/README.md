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

## Database foundation

- SQLAlchemy 2.x declarative base: `app.db.base.Base`
- PostgreSQL engine: `app.db.session.engine`
- Request-scoped session dependency: `app.db.session.get_db`
- Database URL is loaded from the `DATABASE_URL` environment variable.
- Initial ORM models are registered in `app.models` for users, diseases, symptoms, predictions, skin-image metadata, ranked results, and feedback.
- The schema overview and privacy/safety decisions are documented in `../docs/architecture/database-schema.md`.
- Alembic is included as a dependency; migration configuration and the first migration are the next database step.

The engine uses `pool_pre_ping` and does not establish a network connection merely by being imported.
Each API request that uses `get_db` receives its own session, which is closed after the request.

## Current scope and safety

This milestone adds an initial ORM schema draft only. No migration has been applied, no patient data
is being stored, and authentication or disease prediction is not implemented.
Do not place real patient data in development or test databases. Production secrets and database
credentials must be stored in the deployment environment, never committed to Git.
