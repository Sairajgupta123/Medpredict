import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_BASE_URL, SESSION_COOKIE } from "@/lib/auth-proxy";

function privateJson(body: unknown, init: ResponseInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Cache-Control", "private, no-store, max-age=0");
  headers.set("Pragma", "no-cache");
  return NextResponse.json(body, { ...init, headers });
}


type RouteContext = { params: Promise<{ predictionId: string }> };

export async function POST(request: Request, context: RouteContext) {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return privateJson({ detail: "Invalid request origin." }, { status: 403 });
  }

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return privateJson({ detail: "Authentication required." }, { status: 401 });
  }

  const { predictionId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(predictionId)) {
    return privateJson({ detail: "Image history item not found." }, { status: 404 });
  }

  try {
    const upstream = await fetch(
      `${API_BASE_URL}/skin-images/${encodeURIComponent(predictionId)}/revoke-review-consent`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(8_000),
      },
    );
    const body = await upstream.json().catch(() => null);
    return privateJson(
      body ?? { detail: "The consent service returned an invalid response." },
      { status: upstream.status, headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return privateJson(
      { detail: "The consent service is unavailable. Review access has not been confirmed as revoked." },
      { status: 503 },
    );
  }
}
