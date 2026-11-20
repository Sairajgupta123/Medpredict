import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

export const SESSION_COOKIE = "medipredict_session";

type BackendTokenResponse = {
  access_token: string;
  expires_in: number;
  user: unknown;
};

export async function proxyCredentials(
  request: Request,
  endpoint: "login" | "register",
): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Please provide valid JSON." }, { status: 400 });
  }

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${API_BASE_URL}/auth/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict server is unavailable. Please try again shortly." },
      { status: 503 },
    );
  }

  const result = await backendResponse.json().catch(() => null) as
    | BackendTokenResponse
    | { detail?: string }
    | null;

  if (!backendResponse.ok) {
    return NextResponse.json(
      { detail: result && "detail" in result ? result.detail : "Authentication failed." },
      { status: backendResponse.status },
    );
  }

  if (!result || !("access_token" in result) || !("user" in result)) {
    return NextResponse.json({ detail: "The server returned an invalid session response." }, { status: 502 });
  }

  const response = NextResponse.json({
    user: result.user,
    expires_in: result.expires_in,
  });
  response.cookies.set(SESSION_COOKIE, result.access_token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: result.expires_in,
  });
  return response;
}

export async function getSessionUser(): Promise<{
  user: unknown;
  response?: NextResponse;
}> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token) return { user: null };

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${API_BASE_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    return {
      user: null,
      response: NextResponse.json(
        { detail: "The MediPredict server is unavailable." },
        { status: 503 },
      ),
    };
  }

  if (!backendResponse.ok) return { user: null };
  return { user: await backendResponse.json() };
}

export async function getSessionToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(SESSION_COOKIE)?.value ?? null;
}

export type CatalogReviewQueueItem = {
  target_type: "disease" | "symptom" | "disease_symptom";
  target_key: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string | null;
};

export async function getCatalogReviewQueue(): Promise<{
  items: CatalogReviewQueueItem[];
  error: string | null;
}> {
  const token = await getSessionToken();
  if (!token) return { items: [], error: "Your session has expired. Please sign in again." };

  try {
    const response = await fetch(`${API_BASE_URL}/catalog/review/queue`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      return {
        items: [],
        error: response.status === 403
          ? "Your account does not have catalog reviewer access."
          : "The review queue could not be loaded. Please try again.",
      };
    }
    return { items: await response.json() as CatalogReviewQueueItem[], error: null };
  } catch {
    return { items: [], error: "The MediPredict server is unavailable." };
  }
}

