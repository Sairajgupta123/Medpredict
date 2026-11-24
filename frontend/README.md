# MediPredict Frontend

Responsive Next.js application foundation for the MediPredict academic project.

## Requirements

- Node.js 20.9 or newer
- npm 10 or newer
- MediPredict FastAPI backend (required for authentication and API-connected workflows)

## Setup

From this directory:

### Windows PowerShell

    npm install
    Copy-Item .env.example .env.local
    npm run dev

### macOS / Linux

    npm install
    cp .env.example .env.local
    npm run dev

Open http://localhost:3000.

## Available scripts

- npm run dev — start the local development server.
- npm run build — create a production build.
- npm run start — serve the production build.
- npm run typecheck — run TypeScript checks without emitting files.

## Current frontend scope

- Responsive public landing page and authenticated project workspace.
- Shared site header and accessible skip link.
- HttpOnly-cookie login, registration and logout foundation.
- Symptom phrase review prototype and approved-catalog overlap display.
- Consent-first private skin-image intake and owner-scoped image-history controls.
- Dedicated reviewer console for technical image capture review.
- White, forest-green and soft-mint design system with mobile layouts.

The application does not perform skin disease classification, diagnosis, triage or treatment recommendations. Image capture warnings and human review outcomes are technical workflow signals only.

## Symptom phrase review prototype

Open `/symptom-checker` from the workspace dashboard. The page collects a short symptom description and three self-reported context fields: duration, perceived severity and onset. “Not sure” is available for every field.

The browser sends the text and context to the same-origin Next.js route `/api/symptoms/normalize`, which validates the fields and forwards them to FastAPI `POST /api/v1/symptoms/normalize`. The route does not store submitted text and disables upstream fetch caching. Keep request-body logging disabled in any reverse proxy, hosting platform or observability layer used for this application. A read-only catalogue is available through `/api/symptoms/catalog`, backed by FastAPI `GET /api/v1/symptoms/catalog`; the page uses it to display the supported symptom labels grouped by category. Selecting a label appends it to the description but does not confirm its presence or create a diagnosis.

The context values are user descriptions only; they are not measurements, clinical severity scores or triage signals. The response displays them back without clinical interpretation. This is phrase recognition only: no disease prediction, diagnosis, severity assessment, triage or treatment recommendation is performed. After phrase review, the page lets the user locally mark each recognized or contextual mention as present, absent or unsure. These confirmations remain only in browser component state: they are not sent to the backend, persisted, or used to generate a prediction. A missing phrase match does not mean the person has no symptoms. The vocabulary and contextual cue rules are not clinically validated.


## API configuration

Set NEXT_PUBLIC_API_BASE_URL to the backend API root, for example:

    NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1

The API helper is a foundation for non-sensitive typed requests. Do not store bearer tokens in localStorage; authenticated API requests use server-side access to the HttpOnly session cookie.


## Authentication flow

The frontend includes registration, email verification, login, profile lookup and logout
flows backed by the FastAPI authentication endpoints.

- Browser credentials are posted to same-origin Next.js route handlers.
- The route handlers call the FastAPI authentication endpoints server-to-server.
- Registration creates the account and requests a verification email, but does not establish
  a browser session or expose the backend access token to client JavaScript.
- The user verifies the email and then signs in. Only a successful login sets the
  HttpOnly, SameSite=Lax session cookie.
- The dashboard resolves the signed-in profile server-side.
- Logout revokes the backend session and clears the browser cookie.
- Login, registration, email-verification and logout POST routes validate the request Origin.
- Password recovery is available at `/reset-password`; its same-origin proxy routes enforce request-origin checks, bounded JSON bodies and upstream timeouts. The backend issues single-use, 30-minute reset tokens, applies per-email rate limits and revokes existing access tokens after a successful password change.

For local development, run the FastAPI backend at http://localhost:8000 and the Next.js
frontend at http://localhost:3000. Configure `NEXT_PUBLIC_API_BASE_URL` in `.env.local`.
If the frontend and API use separate container networks, set
`MEDIPREDICT_API_INTERNAL_URL` to the private backend URL for server-side requests.

The current session cookie contains the backend's short-lived bearer access token. A production
deployment still needs HTTPS, secret rotation, operational email-delivery verification, account
recovery UX, abuse monitoring, security review, and a deliberate refresh/revocation strategy.
Production configuration requires verified email before authenticated API access; configure and
test the SMTP provider before opening registration.
Do not treat the current authentication foundation as a completed production identity system.


## Private skin-image intake and owner history

Signed-in users can open `/skin-image` from the workspace. The page accepts JPEG, PNG and WebP images up to 8 MiB, shows a local-only preview, and requires three separately explained choices before submission:

- `image-processing-v1`: receipt, validation, sanitization and private storage.
- `image-history-v1`: private history and retention.
- `image-review-v1`: image-specific technical capture-quality review by an authorized human reviewer.

The browser posts multipart data to the same-origin `/api/skin-images/intake` route. The route validates the request origin, requires the HttpOnly session cookie, rejects unexpected or duplicate form fields, enforces the upload size and media-type allowlist, and forwards the request server-to-server with the bearer token. It does not expose the bearer token to client JavaScript. The backend remains responsible for decoding and sanitizing the image, checking metadata, and storing it in private object storage.

The intake page reports success only when the backend confirms `storage_status=stored`. Basic capture warnings are advisory, not clinical quality scores. A successful upload is not a diagnosis or disease prediction.

The owner history page is `/history/skin-images`. It lists only the signed-in user's image/combined history metadata and provides a separate action to revoke human-review consent for an individual submission. Revocation is confirmed only after the backend acknowledges it; reviewer access for that exact image is disabled. The page does not display image bytes, object keys or reviewer notes. Image-history deletion remains a separate operation and is not represented as part of review-consent revocation.

Private image storage must be configured on the backend before intake can succeed. See `backend/README.md` and `docs/architecture/prediction-pipeline.md` for the private S3 adapter, encryption, retention worker and operational prerequisites.


## Skin-image reviewer console and audit trail

Eligible reviewer and administrator accounts can open `/review/skin-images`. Administrators can assign a pending image to a verified reviewer only after granting an exact-prediction `skin_image` scope. Reviewers see only their assigned queue entries. The technical review form accepts only capture outcomes (`capture_adequate` or `unable_to_assess`) and a bounded operational reason; it does not accept diagnosis or disease labels.

The queue links to `/review/skin-images/audit`. The audit page requests `GET /skin-images/review/audit` server-side using the HttpOnly session cookie. Administrators see the complete bounded feed; reviewers see events where they were the actor or assigned reviewer. Each row identifies the actor, role, event, opaque submission reference, reason and timestamp. The page does not retrieve image bytes or expose storage keys.

A successful private image retrieval creates an `image_accessed` event only after object integrity and decoded format checks succeed. This confirms a server-side retrieval, not that a person viewed the complete image. Failed or unauthorized requests are not recorded as successful accesses. Audit events are retained as operational records, not a tamper-proof external compliance archive.
