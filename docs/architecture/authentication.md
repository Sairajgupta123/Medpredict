# MediPredict authentication design

**Status:** Initial email/password authentication is implemented on `develop`. This is an academic
project foundation, not a production security certification.

## Current endpoints

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Public | Create an account and issue an access token |
| POST | `/api/v1/auth/login` | Public | Verify credentials and issue an access token |
| POST | `/api/v1/auth/logout` | Bearer token | Revoke all access tokens for the account |
| GET | `/api/v1/auth/me` | Bearer token | Return the authenticated account profile |
| PATCH | `/api/v1/auth/me` | Bearer token | Update or clear the account display name |

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
4. Reject missing, inactive, or invalid accounts with the same HTTP 401 message.
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

## Current account states

- `is_active`: inactive accounts cannot log in or access protected routes.
- `email_verified`: defaults to false. Email verification is not implemented yet; do not treat
  this field as proof that an address has been verified.
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

- Email verification or verified-email enforcement
- Refresh tokens and refresh-token rotation
- Per-device session management; logout currently revokes all account access tokens
- IP/network-level login and registration rate limiting, distributed abuse detection, and alerting
- Multi-factor authentication
- Admin roles and role-based access control
- Account export/deletion workflow and associated prediction-data retention handling
- Security event audit logging

Password-reset-driven access-token revocation and account-wide logout are implemented through per-user token versions. Logout revokes every access token for the account, not only the token used to call the endpoint. The frontend logout route calls the backend revocation endpoint before clearing the HttpOnly session cookie; if the backend is temporarily unavailable, it retains the cookie so revocation can be retried.
Per-device session management is still deferred. Tokens issued
before the token-version rollout do not contain the required `ver` claim and will be rejected
after deployment, requiring users to sign in again. Keep the lifetime short and always use HTTPS
outside local development.

## Privacy notes

Do not include passwords, tokens, raw symptom descriptions, or private image object keys in logs.
A user's authentication identity must not be treated as permission to access every prediction:
resource ownership checks must be added to each history/report endpoint when those features are built.


## Authentication request throttling

The API persists rate-limit buckets in PostgreSQL (SQLite is supported for tests). Keys are
HMAC-SHA256 digests using the application secret; raw email addresses are not stored in the
throttle table.

Current per-identifier limits:

- Login: 10 attempts per normalized email address per 15-minute window.
- Registration: 5 attempts per normalized email address per hour.
- Password-reset request: 3 attempts per normalized email address per hour.

Excess requests receive HTTP 429 with a `Retry-After` header. These limits are shared across
application workers because they are stored in the database, not process memory. They are
account-targeted limits only: they do not stop an attacker rotating email addresses or
distributing requests across IPs. A production deployment still needs trusted edge/WAF
IP-based throttling, monitoring, and abuse response. Do not treat this control as a complete
anti-bot or denial-of-service defense.
