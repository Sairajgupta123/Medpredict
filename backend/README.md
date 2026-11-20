# MediPredict Backend

FastAPI service foundation for the MediPredict project.

## Requirements

- Python 3.11 or newer
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

The API is available at:

- API root: http://127.0.0.1:8000/
- Health check: http://127.0.0.1:8000/api/v1/health
- Interactive Swagger documentation: http://127.0.0.1:8000/docs

## Run tests

From the `backend/` directory:

```bash
pytest
```

## Current scope

This milestone provides application configuration, CORS configuration, an API router, a health endpoint and a basic API test. It does not yet connect to a database or perform disease prediction.
