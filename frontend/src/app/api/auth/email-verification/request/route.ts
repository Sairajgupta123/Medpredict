import { NextResponse } from "next/server";
import { API_BASE_URL } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  let payload: unknown;
  try {
    const raw = await request.text();
    if (raw.length > 4096) {
      return NextResponse.json({ detail: "Request is too large." }, { status: 413 });
    }
    payload = JSON.parse(raw);
  } catch {
    return NextResponse.json({ detail: "Please provide valid JSON." }, { status: 400 });
  }
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    typeof (payload as { email?: unknown }).email !== "string" ||
    (payload as { email: string }).email.length > 320
  ) {
    return NextResponse.json({ detail: "A valid email address is required." }, { status: 422 });
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/auth/email-verification/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const result = await upstream.json().catch(() => null);
    return NextResponse.json(result ?? { detail: "Unable to request verification." }, {
      status: upstream.status,
      headers: { "Cache-Control": "private, no-store, max-age=0" },
    });
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict server is unavailable. Please try again." },
      { status: 503 },
    );
  }
}
