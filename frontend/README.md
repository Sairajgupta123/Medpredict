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

## API configuration

Set NEXT_PUBLIC_API_BASE_URL to the backend API root, for example:

    NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1

The API helper is a foundation only. Authentication token storage, session refresh, prediction requests and file upload flows are not connected yet. Do not store bearer tokens in localStorage; a secure, reviewed session strategy is required before authentication UI is integrated.
