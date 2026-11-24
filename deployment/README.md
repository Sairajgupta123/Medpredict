# Deployment readiness

This directory tracks the deployment gate for the MediPredict prototype. It does **not**
mean that a hosted environment is configured or that the application is production-ready.

## Current release position

- Frontend: Next.js production build and TypeScript checks run in GitHub Actions.
- Backend: FastAPI tests and PostgreSQL migrations run in GitHub Actions.
- API health endpoints:
  - `GET /api/v1/health` checks process liveness without PostgreSQL.
  - `GET /api/v1/health/ready` checks PostgreSQL connectivity.
  - `GET /api/v1/models/status` reports research artifact configuration only; it never loads
    models or enables inference.
- Skin-image intake requires private object storage and authenticated access.
- Symptom text handling is a limited phrase-review prototype, not diagnosis or triage.
- No deployment URL, hosting configuration, or production secrets are maintained here.

## Local integration smoke test

Run PostgreSQL using the repository's database setup, then start the backend and frontend
in separate terminals.

Backend (from `backend/`):

```bash
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend (from `frontend/`):

```bash
npm install
npm run typecheck
npm run build
npm run start
```

Set `DATABASE_URL` and the backend settings from the root `.env.example`. Set
`NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1` in `frontend/.env.local`.
When the frontend and backend use separate container networks, set
`MEDIPREDICT_API_INTERNAL_URL` to the backend's private service URL.

Verify the public, non-sensitive endpoints:

```bash
curl --fail http://127.0.0.1:8000/api/v1/health
curl --fail http://127.0.0.1:8000/api/v1/health/ready
curl --fail http://127.0.0.1:8000/api/v1/models/status
curl --fail http://127.0.0.1:3000/
```

Expected health responses are HTTP 200. The readiness endpoint must not be treated as
successful unless it can execute its database query. Model status must continue to report
`clinical_diagnosis_enabled: false` and `inference_enabled: false` for both research
capabilities until an independently reviewed model release is explicitly implemented.

Then manually verify login, logout, symptom phrase review, skin-image intake denial when
storage is not configured, and owner-scoped history/review authorization using test accounts
and synthetic non-identifiable data only. Never upload real patient images or symptoms to
a test environment without an approved privacy and consent process.

## Scheduled operational jobs

Run the authentication throttle cleanup daily from the backend environment:

```bash
python -m app.workers.auth_rate_limit_cleanup
```

Each run deletes at most 500 throttle rows older than 48 hours and prints only an aggregate
count. Schedule repeated runs if the backlog exceeds one batch. Also configure IP/network-level
limits at the trusted ingress (API gateway, reverse proxy, or WAF); the application-level
per-email limits are not a replacement for edge protection.

When private skin-image storage is deliberately enabled, also schedule the bounded image
retention worker from the backend environment (for example, once daily):

```bash
python -m app.workers.skin_image_retention
```

The worker processes at most 100 expired image records per run by default (maximum 500),
deletes objects through the configured private S3-compatible adapter, revokes expired
reviewer scopes, and reports aggregate counts only. A failed deletion remains marked
`deletion_pending` for a later retry; the worker exits non-zero if any deletion failed.
Do not enable image intake until private bucket access, encryption, lifecycle policy,
retention duration, monitoring and recovery have been reviewed. The worker is not a
substitute for an object-store lifecycle policy or an operational alert on repeated failures.

## Production gate — not yet cleared

Before exposing the application publicly, complete and independently verify all of the
following:

- [ ] Deploy frontend and API behind HTTPS with trusted certificates.
- [ ] Configure a managed PostgreSQL database, backups, restore test, migrations and
      least-privilege credentials.
- [ ] Set a unique random `APP_SECRET_KEY` (at least 32 characters); rotate any secret
      that may have been used outside local development.
- [ ] Set `REQUIRE_VERIFIED_EMAIL=true`, configure working SMTP host/sender with STARTTLS,
      and verify the full registration → email verification → login flow. Production API
      startup now fails closed when email verification, PostgreSQL, HTTPS origins or SMTP
      requirements are missing.
- [ ] Set exact production `CORS_ORIGINS` and `FRONTEND_BASE_URL`; do not use wildcards
      with credentialed requests.
- [ ] Configure secure cookie behavior for the actual frontend/API topology and verify
      CSRF/origin protections in the deployed environment.
- [ ] Configure the trusted reverse proxy to overwrite (not append or pass through
      client-supplied) `X-Forwarded-Proto`, preserve the canonical `Host`, and accept
      forwarded headers only from known proxy hops; verify same-origin checks over HTTPS.
- [ ] Configure trusted-ingress IP/network rate limiting, schedule the daily
      `python -m app.workers.auth_rate_limit_cleanup` job, and monitor abuse; complete
      account recovery, email verification,
      and a reviewed token refresh/revocation design.
- [ ] If image intake is enabled, configure a private encrypted object bucket, public
      access blocking, least-privilege IAM, retention/deletion jobs, lifecycle policy,
      backups, and access audit monitoring.
- [ ] Verify that logs, traces, analytics and error reporting never capture passwords,
      bearer tokens, symptom text, image bytes, object keys or other sensitive payloads.
- [ ] Complete security, privacy, accessibility and operational reviews; document incident
      response and a tested rollback procedure.
- [ ] Keep clinical diagnosis, triage, treatment advice and model inference disabled unless
      the relevant datasets, model artifacts, validation, clinical oversight and governance
      have been independently approved.

## Release evidence

Record the deployed commit SHA, frontend URL, API URL, migration revision, CI run links,
smoke-test timestamp and reviewer sign-off in the release record when a real environment
has been provisioned. Do not place credentials, patient data, or private object URLs here.
