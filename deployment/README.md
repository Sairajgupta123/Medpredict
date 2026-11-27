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

## PostgreSQL backup and restore

See [`postgres-backup-restore.md`](postgres-backup-restore.md) for the operator runbook and guarded scripts:

- `bash deployment/postgres-backup.sh` creates a custom-format backup and SHA-256 checksum with bounded local retention.
- `bash deployment/postgres-restore.sh` verifies the checksum and restores only after an explicit `ALLOW_DATABASE_RESTORE=YES` acknowledgement. Use a newly provisioned, isolated, empty database; never target production.
- Both scripts require a protected `PGPASSFILE` and reject inline URL passwords. Backups remain local until an operator copies them to separately encrypted storage.

These scripts do not replace managed PostgreSQL point-in-time recovery, off-site encrypted storage, scheduled execution, or a successful restore drill. Keep the production gate blocked until those controls are configured and tested.

## Database connection and migration operations

The API uses SQLAlchemy connection pre-ping, a bounded connection pool, a 30-second pool wait limit, a 30-minute connection recycle interval, and a 5-second PostgreSQL connection timeout by default. Tune these settings to the managed database connection limit and number of API replicas. The combined maximum is approximately `replicas × (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)`. Keep that total below the database application connection budget, leaving capacity for migrations, workers, monitoring, and administration.

Configure these environment variables per deployment:

- `DATABASE_POOL_SIZE` (default 5; allowed 1–50)
- `DATABASE_MAX_OVERFLOW` (default 10; allowed 0–100)
- `DATABASE_POOL_TIMEOUT_SECONDS` (default 30; allowed 1–120)
- `DATABASE_POOL_RECYCLE_SECONDS` (default 1800; allowed 60–86400)
- `DATABASE_CONNECT_TIMEOUT_SECONDS` (default 5; allowed 1–30)

Run migrations as a one-off release step, not independently in every API replica:

```bash
cd backend
alembic upgrade head
alembic current
```

Do not start or route traffic to the new API release until migrations succeed and readiness returns HTTP 200. Prefer backward-compatible expand/contract migrations. A failed migration requires operator review; do not blindly downgrade production schema or automatically roll back data changes. Restore a verified backup into an isolated environment before attempting recovery.

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

## Ingress and client-IP trust boundary

The repository currently contains no reverse-proxy, API-gateway, WAF, or container
ingress configuration. The API therefore does not derive a client identity from
`X-Forwarded-For` or other forwarded-client headers, and its authentication
throttles remain per-email only. Do not enable framework-level forwarded-header
trust or add IP-based application throttling until the hosting topology and exact
trusted proxy hop count are known.

At deployment, configure the edge to:
- discard client-supplied forwarding headers and write canonical values itself;
- expose the API only through the trusted ingress (or explicitly document any
  direct-access exception);
- enforce per-IP/network limits for registration, login, verification and reset
  endpoints, with stricter controls for credential attempts;
- pass forwarded headers only from documented proxy addresses and configure the
  ASGI server's trusted-proxy allowlist to those addresses only;
- test direct-origin access, spoofed forwarding headers, IPv4/IPv6 behavior and
  legitimate shared-NAT traffic before enabling the policy.

Until this is verified, per-email throttling is only a supplemental control and
must not be represented as protection against distributed or email-rotation abuse.

## Frontend session and browser-request boundary

The frontend auth proxy keeps the bearer token in the `medipredict_session`
HttpOnly cookie; browser JavaScript receives only the user/session metadata.
The cookie uses `SameSite=Lax`, `Path=/`, and the `Secure` attribute in
production. Login and registration are bounded same-origin JSON proxies, and
only an explicit login creates a browser session. Logout revokes the upstream
session before clearing the cookie; transient upstream failures preserve the
cookie so the user can retry. Authenticated account deletion clears the browser
cookie only after the upstream request succeeds.

All frontend state-changing API route handlers must validate the browser
`Origin` against the externally visible `Host` and protocol before forwarding
the request. The current route audit covers login, registration, logout,
verification, password reset, account deletion, skin-image intake and consent
revocation, symptom normalization and catalog matching. Private account export
and session/profile reads are GET-only and require the HttpOnly session cookie.
Keep this inventory synchronized whenever a new state-changing route is added.

The origin helper reads the first `X-Forwarded-Proto` value when present because
Next.js may run behind an internal HTTP hop. This header is security-sensitive:
the public ingress must overwrite client-supplied forwarded-protocol headers,
preserve the canonical Host, and be the only network path to the frontend.
Do not treat the application check as proof of proxy trust; verify spoofed
forwarded headers and HTTPS behavior at the deployed edge. The repository's
production smoke script exercises missing, malformed and cross-origin Origin
rejections, but does not replace those ingress tests.

## Scheduled operational jobs

Run the account-erasure worker every 15 minutes from the backend environment:

```bash
python -m app.workers.account_deletion
```

It claims at most 25 pending or abandoned requests per run (maximum batch size 100),
revokes reviewer access before deleting private objects, retries storage failures, and
prints aggregate counts only. Alert on repeated failures and ensure the worker has the
same database access and private object-store permissions as the API. Do not report an
account as fully erased until the request reaches `completed`.

Run the authentication throttle and email-verification token cleanups daily:

```bash
python -m app.workers.auth_rate_limit_cleanup
python -m app.workers.email_verification_cleanup
```

Each job deletes a bounded batch and prints aggregate counts only. Schedule repeated
runs if a backlog exceeds one batch.


Also configure IP/network-level limits at the trusted ingress (API gateway, reverse proxy, or WAF); the application-level per-email limits are not a replacement for edge protection.

When private skin-image storage is deliberately enabled, also schedule the bounded image
retention worker from the backend environment (for example, every 15 minutes):

```bash
python -m app.workers.skin_image_retention
```

The worker processes at most 100 expired image records per run by default (maximum 500),
deletes objects through the configured private S3-compatible adapter, revokes expired
reviewer scopes, and reports aggregate counts only. A failed deletion remains marked
`deletion_pending` for a later retry; the worker exits non-zero if any deletion failed.
A pending deletion is leased using its persisted request timestamp: another retention
worker will not reclaim it immediately, and an abandoned/failed claim becomes eligible
again after two hours. Schedule the worker frequently enough to meet the documented
retention recovery target and alert on repeated failures.
Do not enable image intake until private bucket access, encryption, lifecycle policy,
retention duration, monitoring and recovery have been reviewed. The worker is not a
substitute for an object-store lifecycle policy or an operational alert on repeated failures.

## Privacy-safe worker execution wrapper

For scheduled execution, prefer the allowlisted wrapper so the scheduler receives a
bounded duration, exit status and aggregate-only summary without replaying raw worker
stderr or tracebacks:

```bash
bash deployment/run-worker.sh account-deletion
bash deployment/run-worker.sh skin-image-retention
bash deployment/run-worker.sh auth-rate-limit-cleanup
bash deployment/run-worker.sh email-verification-cleanup
```

Set `WORKER_TIMEOUT_SECONDS` per job (default 900; allowed 1–86400). The wrapper
accepts only the four named worker jobs, propagates non-zero worker/timeout exit codes,
and emits a low-cardinality `worker_run` status line with duration. It prints only
recognized aggregate summary lines; raw exception text and stderr are discarded to
avoid leaking identifiers or credentials into scheduler logs. Use the scheduler's
exit-code alerting and retain aggregate logs according to the incident policy.

## Private S3 image deletion and versioning

The S3 adapter uses server-side encryption and never sets a public ACL. For
unversioned buckets, deletion uses the idempotent `DeleteObject` operation.
For buckets with versioning enabled or suspended, deletion enumerates versions
and delete markers for the exact opaque image key and permanently removes them
in bounded batches. A partial version-delete response is treated as a failure,
so the retention/account-erasure worker leaves the database record pending for
retry instead of marking the image deleted.

If bucket versioning is enabled or suspended, grant the worker narrowly scoped
permissions for `GetBucketVersioning`, `ListBucketVersions` on the image
bucket, and `DeleteObjectVersion` only under the `skin-images/*` prefix, in
addition to the required object put/get/delete permissions. Do not grant
bucket-wide administrative access. Verify the policy against the actual cloud
provider and test denied/partial-delete behavior before enabling image intake.

Configure an independent bucket lifecycle policy for current and noncurrent
versions, expired delete markers, and incomplete multipart uploads. The
application retention worker remains the authoritative per-record expiry and
consent workflow; a bucket lifecycle policy is defense in depth and must not
delete objects before the disclosed application retention deadline. Confirm
lifecycle behavior with synthetic objects in a non-production bucket.

## Operational monitoring and alerting

The application exposes liveness and database-readiness separately; configure the
platform to probe `/api/v1/health` for process liveness and
`/api/v1/health/ready` for traffic readiness. A readiness failure should remove
the instance from service and page the database/platform owner according to the
deployment's incident policy. Do not expose database exception details in probes.

For scheduled workers, capture exit code, start/end time, duration and aggregate
counts from stdout/stderr. Never forward raw exception payloads, request bodies,
email addresses, image identifiers, object keys or tokens into alert labels.

Alert and investigate when:
- any account-deletion batch exits non-zero or reports `failed > 0`;
- pending account-deletion backlog grows or its oldest request exceeds the
  operator-defined erasure service target;
- authentication-throttle or verification-token cleanup repeatedly fails or
  leaves a growing backlog;
- any image-retention batch exits non-zero, reports failed deletions, or leaves
  `deletion_pending` objects beyond the configured operational recovery target;
- database readiness, migration checks, backup verification or restore drills fail.

Dashboard at minimum: API liveness/readiness, HTTP 5xx and 429 rates, worker
success/failure counts and duration, deletion backlog age, expired-image cleanup
counts, database connection saturation, backup age/checksum status and last
successful restore-drill timestamp. Keep labels aggregate and low-cardinality;
do not use user IDs, emails, symptoms or image IDs as metric dimensions.

A green health probe does not prove that scheduled workers, object storage,
backups, SMTP delivery or clinical governance are healthy. Track each as a
separate operational dependency and keep the release gate blocked until verified.

## Production gate — not yet cleared

Before exposing the application publicly, complete and independently verify all of the
following:

- [ ] Deploy frontend and API behind HTTPS with trusted certificates.
- [ ] Configure a managed PostgreSQL database, backups, restore test, migrations and
      least-privilege credentials, TLS-enforced connections (sslmode=require or stronger), and verified backups.
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
      access blocking, least-privilege IAM, `SKIN_IMAGE_RETENTION_DAYS` (1–3650),
      retention/deletion jobs, lifecycle policy, backups, and access audit monitoring.
      Production startup fails when a bucket is configured without an explicit retention
      period; intake records expiry per image and discloses the period before consent.
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
