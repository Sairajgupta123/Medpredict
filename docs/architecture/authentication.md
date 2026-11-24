# MediPredict authentication design

**Status:** Initial email/password authentication is implemented on `develop`. This is an academic
project foundation, not a production security certification.

## Current endpoints

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Public | Create an account and issue an access token |
| POST | `/api/v1/auth/login` | Public | Verify credentials and issue an access token |
| POST | `/api/v1/auth/email-verification/request` | Public | Send a generic verification email response |
| POST | `/api/v1/auth/email-verification/confirm` | Public | Consume a one-time email verification token |
| POST | `/api/v1/auth/logout` | Bearer token | Revoke all access tokens for the account |
| GET | `/api/v1/auth/me` | Bearer token | Return the authenticated account profile |
| PATCH | `/api/v1/auth/me` | Bearer token | Update or clear the account display name |
| GET | `/api/v1/auth/me/export` | Bearer token | Download a private JSON export of the account's data |
| POST | `/api/v1/auth/me/deletion-request` | Patient bearer token + current password | Disable account immediately and queue personal-data erasure |

Registration and login accept JSON bodies. Login does not use OAuth form fields.

## Registration flow

1. Validate the email address and password length.
2. Normalize the email address to lowercase.
3. Check for an existing account.
4. Hash the password with Argon2 using `pwdlib`.
5. Store the hash, never the original password.
6. Issue a signed access token after successful account creation.

The database unique constraint remains the final protection against concurrent duplicate
registrations. A conflicting insert is rolled back and returned as HTTP 409.

## Login flow

1. Normalize the submitted email.
2. Fetch the account by email.
3. Verify the password hash.
4. Reject missing, inactive, invalid, or (when `REQUIRE_VERIFIED_EMAIL=true`) unverified accounts with the same HTTP 401 message.
5. Update the last-login timestamp.
6. Issue a short-lived JWT.

For unknown emails, the service verifies against a fixed dummy Argon2 hash to reduce obvious
timing differences between known and unknown accounts. This is not a substitute for rate limiting.

## Access token

- Algorithm: HS256
- Subject: user UUID
- Issuer: `medipredict-api`
- Token type: `access`
- Claims: `sub`, `iss`, `type`, `iat`, `exp`, `ver` (per-user token version)
- Default lifetime: 30 minutes
- Configurable through `ACCESS_TOKEN_EXPIRE_MINUTES`
- Signing key: `APP_SECRET_KEY`

Production configuration rejects the built-in development secret and requires at least 32
characters. Use a cryptographically random secret from a secret manager or deployment environment.
Never commit real credentials.

## Profile update

The authenticated account may update its own `display_name` using `PATCH /api/v1/auth/me`.
The request accepts a trimmed non-empty display name, or explicit `null` to clear it. Empty
payloads and whitespace-only names are rejected. Email, account status, verification state, and
password hash are not writable through this endpoint.

## Email verification

The API provides POST `/api/v1/auth/email-verification/request` and
POST `/api/v1/auth/email-verification/confirm`. Verification tokens are random, expire after
30 minutes, are stored only as SHA-256 digests, and are single-use. Re-requesting a link
invalidates earlier unused links. The request endpoint returns the same HTTP 202 response for
unknown, inactive, and already verified accounts. SMTP failures invalidate the undelivered
token and do not reveal account existence.

Set REQUIRE_VERIFIED_EMAIL=true to reject login for unverified accounts using the same
generic HTTP 401 response as invalid credentials. It defaults to false to preserve local
development and existing deployments; production deployments that require verified identities
must explicitly enable it and configure SMTP.

## Roles and authorization

Accounts use three roles: `patient`, `reviewer`, and `admin`. Patient accounts cannot
access governance operations. Reviewer routes require the reviewer role and, for catalog or
skin-image work, an active scope grant for the relevant item. Administrative governance and
reviewer-scope management routes require the admin role. Role changes are separately recorded
in role-provisioning events; public profile updates cannot change a user's role.

## Current account states

- `is_active`: inactive accounts cannot log in or access protected routes.
- `email_verified`: defaults to false and becomes true only after a valid, single-use email verification token is consumed.
- `last_login_at`: updated after successful login.
- `token_version`: monotonically incremented when the password is reset or the account logs out; protected routes compare
the JWT `ver` claim with this database value.

## Password reset foundation

The backend now has a `password_reset_tokens` table and token lifecycle helpers. Tokens are
created with a cryptographically random value, only a SHA-256 digest is stored, unused prior
tokens are invalidated when a replacement is issued, and consumption is guarded by a conditional
database update so a token can succeed only once. Tokens expire after 30 minutes by default.

The public endpoints are `POST /api/v1/auth/password-reset/request` and
`POST /api/v1/auth/password-reset/confirm`. The request endpoint returns the same HTTP 202
message for known, unknown, and inactive accounts. It never returns the raw token. The
confirmation endpoint updates the Argon2 password hash and consumes the token in the same
database transaction. SMTP delivery is configured through `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER_EMAIL`, and `SMTP_USE_TLS`; the frontend reset
URL is built from `FRONTEND_BASE_URL`. If SMTP is not configured or delivery fails, the API
still returns the generic response and does not log the token or recipient.

## Security boundaries and deferred work

The current implementation does not yet include:

- Refresh tokens and refresh-token rotation
- Per-device session management; logout currently revokes all account access tokens
- IP/network-level login and registration rate limiting, distributed abuse detection, and alerting
- Multi-factor authentication
- Self-service account deletion and its asynchronous private-image cleanup workflow
- Security event audit logging

Password-reset-driven access-token revocation and account-wide logout are implemented through per-user token versions. Logout revokes every access token for the account, not only the token used to call the endpoint. The frontend logout route calls the backend revocation endpoint before clearing the HttpOnly session cookie; if the backend is temporarily unavailable, it retains the cookie so revocation can be retried.
Per-device session management is still deferred. Tokens issued
before the token-version rollout do not contain the required `ver` claim and will be rejected
after deployment, requiring users to sign in again. Keep the lifetime short and always use HTTPS
outside local development.

## Privacy notes

Do not include passwords, tokens, raw symptom descriptions, or private image object keys in logs.
Prediction-history endpoints enforce owner-scoped access and omit retained health inputs from list responses. Any new history, report, export, or image endpoint must apply an equivalent ownership check before reading or mutating a user's data.


## Authentication request throttling

The API persists rate-limit buckets in PostgreSQL (SQLite is supported for tests). Keys are
HMAC-SHA256 digests using the application secret; raw email addresses are not stored in the
throttle table.

Current per-identifier limits:

- Login: 10 attempts per normalized email address per 15-minute window.
- Registration: 5 attempts per normalized email address per hour.
- Password-reset request: 3 attempts per normalized email address per hour.

Excess requests receive HTTP 429 with a `Retry-After` header containing the remaining window duration. These limits are shared across
application workers because they are stored in the database, not process memory. They are
account-targeted limits only: they do not stop an attacker rotating email addresses or
distributing requests across IPs. A production deployment still needs trusted edge/WAF
IP-based throttling, monitoring, and abuse response. Do not treat this control as a complete
anti-bot or denial-of-service defense.


### Throttle data lifecycle

Rate-limit rows are retained briefly for operational throttling and cleanup. Run
`python -m app.workers.auth_rate_limit_cleanup` daily from the deployment scheduler; each
invocation deletes at most 500 rows whose windows ended more than 48 hours ago. The worker
prints aggregate counts only and can be safely run repeatedly. Increase the scheduler
frequency or invoke additional batches if a backlog develops.

The per-email counters are not sufficient against distributed credential stuffing or
email-rotation abuse. Production ingress must additionally apply IP/network-level limits
at a trusted reverse proxy, API gateway, or WAF. The application must not trust arbitrary
client-supplied forwarding headers for client IP identity. Monitor 429 rates and authentication
failures without logging passwords, tokens, raw emails, or private health data.


### Email verification token lifecycle

Run `python -m app.workers.email_verification_cleanup` daily from the deployment scheduler.
Each invocation deletes at most 500 tokens that expired or were consumed more than 48 hours
ago. Recent consumed tokens are retained briefly to support replay rejection and operational
review. The worker logs aggregate deletion counts only; it never prints token digests, raw
tokens, email addresses, or account identifiers. Run additional bounded batches if a backlog
develops.


## Personal data export

An authenticated account owner can request `GET /api/v1/auth/me/export` to receive a
JSON attachment containing their profile, owned prediction records, retained symptom text,
result explanations, image metadata, and consent history. The query is scoped to the
authenticated user ID. It deliberately excludes password hashes, access/reset/verification
tokens, private object-storage keys, raw image bytes, and reviewer identifiers. The response
uses `Cache-Control: private, no-store`. Image bytes remain in private object storage and are
not embedded in the JSON export; a separate authorized image-export workflow would be needed
if that capability is introduced.


## Account deletion safety requirements

Self-service account deletion is not exposed yet. A database-only delete or a broad
ORM cascade would be unsafe for this schema:

- Skin-image bytes are stored outside the relational database. The existing private
  storage adapter's `delete_private` operation is idempotent, but deletion must be
  confirmed before the corresponding database history is removed.
- Image records in unknown, pending-upload, or failed storage states must not be
  treated as successfully erased. The existing history deletion service deliberately
  blocks unverified storage states and retains a durable `deletion_pending` marker
  when object deletion fails.
- Reviewer-scope grants, scope events, catalog review events, reference-link audit
  events, and role-provisioning events contain restrictive foreign keys to user
  accounts. Deleting a reviewer or administrator without a governance transfer
  would break attribution and/or violate referential integrity.
- Prediction history has owner-scoped health inputs and consent events. Any
  deletion workflow must handle the owned prediction graph and image objects
  together, while preserving only the minimum legally/operationally required
  audit evidence under an explicit retention policy.
- Account access must be revoked immediately when a deletion request is accepted.
  A queued request must remain retryable and must not be marked complete until
  external object deletion and the database cleanup have both succeeded.

The intended implementation is a patient-only, password-confirmed request followed
by bounded asynchronous processing. Reviewer and administrator accounts require
separate assignment transfer and audit-retention handling; they must not be silently
anonymized or deleted through the patient self-service path. Until that workflow,
storage reconciliation, and tests are complete, account deletion must be treated as
unsupported rather than implying that deactivation is erasure.


## Patient account deletion request

An authenticated patient can submit `POST /api/v1/auth/me/deletion-request` with the
current password. The API rejects reviewer/admin roles, validates the password, marks
the account inactive, increments its token version, and persists a unique pending
request in the same transaction. The existing session is therefore revoked immediately.
Repeated requests while pending return the same queued state.

Run `python -m app.workers.account_deletion` from a scheduled worker (recommended
every 15 minutes while requests are pending). Each batch is bounded to 25 requests.
The worker deletes each private image object before deleting the associated prediction
records. Only storage states `stored`, `deletion_pending`, and `deleted` are eligible;
unknown, failed, and pending-upload states remain queued for manual reconciliation.
Storage failures retain the request and retry marker; aggregate output contains no
account identifiers or health information.

After all image objects are confirmed deleted, prediction-owned database rows are
removed. The user row is retained as a non-login audit tombstone because immutable
review/governance records use restrictive actor foreign keys. Its email is replaced
with a unique invalid-domain address, display name is cleared, password hash is
rotated to an unreturned random value, verification is cleared, and access tokens
are revoked. This is pseudonymization plus removal of account-owned health records,
not a promise to erase legally/operationally retained audit events or backups.
Reviewer and administrator accounts remain ineligible for self-service deletion
until assignment transfer and governance retention are separately implemented.
