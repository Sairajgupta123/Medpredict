# MediPredict authentication design

**Status:** Initial email/password authentication is implemented on `develop`. This is an academic
project foundation, not a production security certification.

## Current endpoints

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Public | Create an account and issue an access token |
| POST | `/api/v1/auth/login` | Public | Verify credentials and issue an access token |
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
- Claims: `sub`, `iss`, `type`, `iat`, `exp`
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

## Security boundaries and deferred work

The current implementation does not yet include:

- Email verification or verified-email enforcement
- Password reset and recovery
- Refresh tokens, rotation, or token revocation
- Server-side logout/session invalidation
- Login/registration rate limiting and abuse detection
- Multi-factor authentication
- Admin roles and role-based access control
- Account export/deletion workflow and associated prediction-data retention handling
- Security event audit logging

Until token revocation or refresh-token sessions are implemented, a stolen access token remains
usable until it expires. Keep the lifetime short and always use HTTPS outside local development.

## Privacy notes

Do not include passwords, tokens, raw symptom descriptions, or private image object keys in logs.
A user's authentication identity must not be treated as permission to access every prediction:
resource ownership checks must be added to each history/report endpoint when those features are built.
