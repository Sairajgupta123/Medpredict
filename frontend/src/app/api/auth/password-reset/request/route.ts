import { NextResponse } from "next/server";
import { API_BASE_URL } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";
import { readBoundedJsonBody } from "@/lib/bounded-json";

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  const parsed = await readBoundedJsonBody(request);
  if (!parsed.ok) {
    return NextResponse.json(
      { detail: parsed.status === 413 ? "Request is too large." : "Please provide valid JSON." },
      { status: parsed.status },
    );
  }
  const payload = parsed.value;
  if (
    !payload || typeof payload !== "object" || Array.isArray(payload) ||
    typeof (payload as { email?: unknown }).email !== "string" ||
    (payload as { email: string }).email.length > 320
  ) {
    return NextResponse.json({ detail: "A valid email address is required." }, { status: 422 });
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/auth/password-reset/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const result = await upstream.json().catch(() => null);
    return NextResponse.json(result ?? { detail: "Unable to request a password reset." }, {
      status: upstream.status,
      headers: { "Cache-Control": "private, no-store, max-age=0" },
    });
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict server is unavailable. Please try again." },
      { status: 503, headers: { "Cache-Control": "private, no-store, max-age=0" } },
    );
  }
}
