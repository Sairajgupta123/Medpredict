# MediPredict Frontend

Responsive Next.js application foundation for the MediPredict academic project.

## Requirements

- Node.js 20.9 or newer
- npm 10 or newer
- MediPredict FastAPI backend (only required for future API-connected workflows)

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

- Responsive public landing page.
- Shared site header and accessible skip link.
- Project workspace/dashboard overview.
- Reusable typed API request helper and catalog response types.
- White, forest-green and soft-mint design system.
- Reduced-motion support and mobile layout.

The dashboard intentionally describes symptom analysis, skin image analysis and reviewed guidance as in development. No fake prediction results, upload controls, medical advice, or authentication claims are presented.

## Symptom phrase review prototype

Open `/symptom-checker` from the workspace dashboard. The page collects a short symptom description and three self-reported context fields: duration, perceived severity and onset. “Not sure” is available for every field.

The browser sends the text and context to the same-origin Next.js route `/api/symptoms/normalize`, which validates the fields and forwards them to FastAPI `POST /api/v1/symptoms/normalize`. The route does not store submitted text and disables upstream fetch caching. Keep request-body logging disabled in any reverse proxy, hosting platform or observability layer used for this application. A read-only catalogue is available through `/api/symptoms/catalog`, backed by FastAPI `GET /api/v1/symptoms/catalog`; the page uses it to display the supported symptom labels grouped by category. Selecting a label appends it to the description but does not confirm its presence or create a diagnosis.

The context values are user descriptions only; they are not measurements, clinical severity scores or triage signals. The response displays them back without clinical interpretation. This is phrase recognition only: no disease prediction, diagnosis, severity assessment, triage or treatment recommendation is performed. After phrase review, the page lets the user locally mark each recognized or contextual mention as present, absent or unsure. These confirmations remain only in browser component state: they are not sent to the backend, persisted, or used to generate a prediction. A missing phrase match does not mean the person has no symptoms. The vocabulary and contextual cue rules are not clinically validated.


## API configuration

Set NEXT_PUBLIC_API_BASE_URL to the backend API root, for example:

    NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1

The API helper is a foundation only. Authentication token storage, session refresh, prediction requests and file upload flows are not connected yet. Do not store bearer tokens in localStorage; a secure, reviewed session strategy is required before authentication UI is integrated.


## Authentication flow

The frontend includes login and registration pages backed by the API's `/auth/login`,
`/auth/register`, and `/auth/me` endpoints.

- Browser credentials are posted to same-origin Next.js route handlers.
- The route handlers call the FastAPI authentication endpoints server-to-server.
- The returned access token is stored in an HttpOnly, SameSite=Lax cookie; client-side
  JavaScript cannot read it.
- The dashboard resolves the signed-in profile server-side.
- Logout clears the session cookie.
- Login, registration and logout POST routes validate the request Origin.

For local development, run the FastAPI backend at http://localhost:8000 and the Next.js
frontend at http://localhost:3000. Configure `NEXT_PUBLIC_API_BASE_URL` in `.env.local`.
If the frontend and API use separate container networks, set
`MEDIPREDICT_API_INTERNAL_URL` to the private backend URL for server-side requests.

The current session cookie contains the backend's short-lived bearer access token. A production
deployment still needs HTTPS, secret rotation, rate limiting and abuse monitoring, email
verification and account recovery, security review, and a deliberate refresh/revocation strategy.
Do not treat the current authentication foundation as a completed production identity system.
