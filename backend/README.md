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

The request body contains `expected_status`, the status observed when the reviewer
opened the queue item, the desired `status` (`draft`, `in_review`, `approved`, or
`retired`), and a reason. The API locks the catalog row during the decision and returns
HTTP 409 if the current status no longer matches `expected_status`; the reviewer must
refresh and reassess instead of overwriting another reviewer's newer decision. The API
derives `reviewed_by` from the authenticated reviewer identity and sets `reviewed_at`
on approval; clients cannot supply or impersonate these audit fields.
Moving an item out of approved state clears its current approval metadata.

Every review action must include a reason of 8–1,000 characters. The decision and its
audit event are committed in the same database transaction. Each event records target type,
target key, previous status, new status, reason, authenticated reviewer ID, and server timestamp.
The history is append-only through the API; there are no update or delete endpoints.
Database constraints also validate both the previous and new lifecycle states and reject
blank audit target keys or reasons.

Authorized reviewers can inspect pending work, filter decision history, and open a reviewed catalog entry:

- `GET /api/v1/catalog/review/queue?status=draft&status=in_review&q=fever&target_type=symptom&offset=0&limit=20`
- `GET /api/v1/catalog/review/history?target_type=disease&date_from=2026-01-01&date_to=2026-12-31&q=source&limit=100`
- `GET /api/v1/catalog/review/history/{event_id}/entry`

The queue is restricted to reviewers/admins and includes draft and in-review entries by default.
Use the optional `target_type` filter (`disease`, `symptom`, or `disease_symptom`), repeat
the `status` query parameter to select one or more valid lifecycle states, and use `q` to search
codes, names, or descriptions. Pagination uses a zero-based `offset` (0–10,000) and a `limit`
of 1–50. Results are globally ordered across the selected categories; the API returns up to one
additional item so clients can determine whether a next page exists. History supports category, exact target key, free-text search over target
key and decision reason, and inclusive UTC date boundaries. A reversed date range is rejected.
Reviewers can see only events created under their own account; administrators can inspect all
events. The entry-detail endpoint checks the event owner before returning the current disease,
symptom, or relationship record, so a reviewer cannot use another reviewer's event ID to read
catalog details. Patients cannot access the queue or review history.
The audit record is operational traceability, not proof of clinical validity or reviewer credentials.
The pending-entry inspection endpoint is
`GET /api/v1/catalog/review/queue/entry?target_type=disease&target_key=...`
(and accepts `symptom` or `disease_symptom` with a composite
`DISEASE_CODE:SYMPTOM_CODE` key). It returns the current pending record, linked disease
and symptom metadata for relationship reviews, and its lifecycle metadata. It enforces the
same active reviewer scope as review decisions and returns only `draft` or `in_review`
records. A missing, out-of-scope, or no-longer-pending record is not exposed.

Catalog entries can be linked to existing `medical_references` through
`catalog_references`. The association supports disease, symptom, and disease-symptom
targets. Each link records the actor and a reason; removals are soft removals, and every
link/remove action appends a `catalog_reference_events` audit record. Re-linking a removed
source reactivates the existing association and appends a new event rather than deleting
history.

Reference registry endpoints:

- `GET /api/v1/catalog/review/references?q=...` — reviewer/admin source search, including
  source review state and review-due metadata.
- `POST /api/v1/catalog/review/queue/entry/references` — attach an existing source to an
  assigned pending catalog entry; requires a reason.
- `POST /api/v1/catalog/review/queue/entry/references/{link_id}/remove` — remove an active
  link with a reason.
- `POST /api/v1/admin/medical-references` — administrator-only source registration.
  New source records always start as `draft` and require a registration reason.
- `GET /api/v1/admin/medical-references` — administrator source registry search/filter.
- `POST /api/v1/admin/medical-references/{reference_id}/review` — administrator source
  lifecycle decision with expected-status conflict protection and a required reason.
- `GET /api/v1/admin/medical-references/{reference_id}/history` — immutable source
  registration and review-state history.

Link operations enforce the same active catalog reviewer scope as review decisions. The
inspection response shows source publisher, URL, evidence type, version, publication/access
dates, review state, reviewer metadata, due date, and the reason the source was linked.
Source registration and attachment do not approve a source or prove clinical validity.
The existing knowledge publication gate remains separate and continues to require approved,
current source records. Source review decisions set reviewer metadata only when the source is
approved; moving it back to draft/in-review/retired clears approval metadata. Every source
registration and status transition appends a `medical_reference_events` record in the same
transaction. Source metadata is versioned by URL/version; create a new version rather than
silently editing the provenance of an existing record. Migrations `0013_catalog_references`
and `0014_medical_reference_audit` create the association and source lifecycle audit tables.


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
`--dry-run` to validate a proposed change without committing it. Before demoting a reviewer,
revoke all active catalog scopes through the administrator workspace; the CLI blocks demotion
while any active scope remains so that a later role re-grant cannot silently restore old access.
The command records the
previous/new role, target account, operator identity, reason, and server timestamp in the
append-only `role_provisioning_events` table in the same transaction as the role update.
The operator identity is asserted by the trusted shell environment; it is not independently
authenticated by the application. Restrict database credentials and shell access to authorized
operations personnel, and preserve database backups and audit records.

This CLI deliberately cannot grant, revoke, or modify the `admin` role. Admin bootstrap or
changes require a separate DBA-controlled process outside the application. Do not promote accounts through ad-hoc
SQL in a production database. Reviewer role assignment alone does not establish clinical
qualification; the organization must verify credentials and scope before granting it.

### Scoped reviewer responsibilities

Reviewer role provisioning and catalog responsibility assignment are separate controls. A
reviewer account does not receive catalog access merely because its role is `reviewer`.
An administrator must grant one or more explicit scopes through the admin workspace or API.

- `GET /api/v1/admin/reviewers` lists active, email-verified reviewer accounts.
- `GET /api/v1/admin/reviewer-scopes` lists current and revoked grants.
- `POST /api/v1/admin/reviewer-scopes` grants a scope.
- `POST /api/v1/admin/reviewer-scopes/{scope_id}/revoke` revokes an active scope.
- `GET /api/v1/admin/reviewer-scopes/history` returns immutable grant/revocation events.

A scope uses one catalog type: `disease`, `symptom`, or `disease_symptom`. A null
`scope_key` grants access to all entries of that type; an exact key limits access to one item.
Relationship keys use `DISEASE_CODE:SYMPTOM_CODE`. Exact assignments are validated against
existing catalog records. Every grant and revocation requires a reason and writes an immutable
audit event in the same database transaction.

Reviewers can only see queue items within their active scopes and can only change entries within
those scopes. Reviewers see their own catalog decision history; administrators can inspect the
full history. Administrators retain unrestricted review access. Patients and reviewers cannot
grant or revoke scopes. Revoked scopes remain in the assignment register and cannot authorize
further actions. Re-granting a previously revoked scope reactivates the existing grant record and
appends a new grant event, preserving the earlier audit history.

The new schema is introduced by migration `0012_reviewer_scopes`. Apply it with the normal
development migration process before using the new admin scope-management page.

### Administrator governance overview

Administrators can inspect operational account and catalog lifecycle metrics through:

```http
GET /api/v1/admin/governance?history_limit=20
```

This endpoint requires an authenticated account with the `admin` role. It returns active and
inactive account counts by role, disease/symptom/association counts by review status, and a
bounded list of recent reviewer-role provisioning events. It does not expose account email
addresses, password data, or role mutation actions. Patients and reviewers receive HTTP 403.
The endpoint is an operational monitoring view; it does not certify reviewer qualifications
or establish clinical validation of any catalog content.

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


## Skin image intake (research-only)

The authenticated multipart endpoint is `POST /api/v1/skin-images/intake`. It accepts one JPEG, PNG or WebP file (maximum 8 MiB), plus separate required form fields for image-processing consent and image-history consent, each with its own policy version. The server decodes and re-encodes the image to remove metadata before sending it to private object storage.

The endpoint is fail-closed unless `SKIN_IMAGE_S3_BUCKET` and `SKIN_IMAGE_S3_REGION` are configured. AWS credentials are resolved through the standard boto3 credential chain (for example, an IAM role); do not put credentials in source control. A custom S3-compatible endpoint must use HTTPS. Encryption defaults to AES256; KMS requires `SKIN_IMAGE_S3_ENCRYPTION=aws:kms` and `SKIN_IMAGE_S3_KMS_KEY_ID`.

Before configuration, provision a private bucket with Block Public Access, restrictive bucket policy, least-privilege IAM permissions, and encryption controls. CI uses a fake storage client and does not verify your cloud account or bucket policy. The endpoint performs image intake only: it does not classify skin lesions, predict disease, or provide a diagnosis. The authenticated history DELETE endpoint removes the private object before deleting its database record. The existing revoke-consent endpoint handles image-history consent by deleting the object before recording revocation; if storage is unavailable or deletion fails, it returns an error and retains a retryable deletion marker.

The owner-only retrieval endpoint is `GET /api/v1/skin-images/{prediction_id}`. It requires a valid bearer token, ownership of the prediction, an image/combined modality, an image row in `stored` state, and currently active `skin_image_history` consent. The service retrieves bytes through the private adapter, enforces the 8 MiB bound, verifies the database SHA-256 digest and decoded image format, and returns `private, no-store` with `nosniff`; it never returns the object key or a public URL. Deleted, pending, failed, unowned, or non-consented records are not retrievable. Retrieval does not invoke a classifier or make a medical assessment.

A bounded retention job is available as `python -m app.workers.skin_image_retention` (run from the `backend/` directory). Configure it through your deployment scheduler only after approving an explicit retention policy and testing the real bucket. It processes at most 100 due objects per run, retries `deletion_pending` objects on later runs, preserves minimal prediction/consent audit metadata, and prints only aggregate counts. Prevent overlapping scheduled runs and alert when the reported failure count is non-zero. CI uses fake storage; it does not prove real AWS permissions, bucket privacy, or provider configuration.

## Human skin-image review workflow

Stored skin images can be assigned by an administrator to an active, email-verified account with the reviewer role:

- POST /api/v1/skin-images/review/{prediction_id}/assign — administrator assigns or reassigns a stored image with an 8–1,000 character operational reason.
- GET /api/v1/skin-images/review/queue — reviewers see only their assigned items; administrators can inspect all assigned items.
- GET /api/v1/skin-images/review/{prediction_id}/image — only the assigned reviewer or an administrator can retrieve the private image while processing consent remains active.
- POST /api/v1/skin-images/review/{prediction_id}/decision — assigned reviewer or administrator records capture_adequate or unable_to_assess, with an audit reason.
- GET /api/v1/skin-images/review/{prediction_id}/events — assigned reviewer and administrators can inspect the append-only assignment/review event history.

The workflow is strictly a technical capture-quality review. capture_adequate does not mean a lesion is benign, malignant, or clinically assessable. No diagnosis, disease label, probability, treatment advice, or clinical interpretation is accepted or produced. Processing consent is checked before queue inclusion, image retrieval, assignment, and review decisions. Reviewers must be explicitly provisioned and verified operationally; the role and email-verification flags alone do not establish clinical qualifications. Administrators are responsible for verifying reviewer credentials and scope before assignment.

Review audit events preserve opaque prediction/image UUID references without foreign keys to the user-history rows, so deleting an image history item does not erase the assignment/review audit trail. The audit stores actor, assignee, event, limited outcome, reason, and timestamp; it does not store image bytes or a public image URL. The image review UI and production reviewer qualification process are not yet implemented.


### Dedicated skin-image reviewer permissions

A general reviewer role or a catalog-review scope does not grant access to patient images. Administrators must grant a separate `skin_image` reviewer scope through `POST /api/v1/admin/reviewer-scopes`. A skin-image scope must use the exact prediction UUID as `scope_key`; broad or null-key image scopes are rejected. This enforces least-privilege access per submission.

The image-review assignment endpoint requires that scope in addition to an active, verified reviewer account. Queue inclusion, private image retrieval, review decisions and audit-history access re-check the active scope. Revoking the scope immediately blocks further reviewer access. When an image is reassigned, the previous reviewer's exact image scope is automatically revoked and an immutable scope event is recorded. The admin review screen grants an exact-image scope before assignment; it does not grant blanket image access.

The scope grant is an application authorization control, not proof of clinical credentials. Administrators must separately verify reviewer qualifications, contractual authorization, training and permitted purpose before granting access. Access logging and audit retention should be monitored under the deployment's privacy policy.


Successful image delivery is also recorded as an `image_accessed` audit event with the authenticated actor, assigned reviewer, submission references, reason and timestamp. Failed or unauthorized requests are not represented as successful image views. The audit event contains no image bytes, public URL or clinical interpretation.

### Separate consent for human image review

Separate `skin_image_processing`, `skin_image_history`, and `skin_image_review` consent purposes are recorded with independent policy versions. The intake endpoint requires all three explicit choices. Human-review queue access, assignment, decisions and private reviewer image retrieval require active processing and human-review consent. The owner can revoke human-review consent at `POST /api/v1/skin-images/{prediction_id}/revoke-review-consent`; this immediately revokes exact-image reviewer scopes while retaining the minimal audit trail. Image-history consent remains a separate control for owner retrieval and retention.
