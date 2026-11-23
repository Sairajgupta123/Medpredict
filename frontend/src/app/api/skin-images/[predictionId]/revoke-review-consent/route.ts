import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_BASE_URL, SESSION_COOKIE } from "@/lib/auth-proxy";

type RouteContext = { params: Promise<{ predictionId: string }> };

export async function POST(request: Request, context: RouteContext) {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Authentication required." }, { status: 401 });
  }

  const { predictionId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(predictionId)) {
    return NextResponse.json({ detail: "Image history item not found." }, { status: 404 });
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
    return NextResponse.json(
      body ?? { detail: "The consent service returned an invalid response." },
      { status: upstream.status, headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return NextResponse.json(
      { detail: "The consent service is unavailable. Review access has not been confirmed as revoked." },
      { status: 503 },
    );
  }
}
