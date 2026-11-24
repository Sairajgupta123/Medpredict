import { NextResponse } from "next/server";
import { API_BASE_URL, readBoundedJson } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";
import { readBoundedJsonBody } from "@/lib/bounded-json";

function noStoreJson(body: unknown, init: ResponseInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Cache-Control", "private, no-store, max-age=0");
  return NextResponse.json(body, { ...init, headers });
}

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return noStoreJson({ detail: "Invalid request origin." }, { status: 403 });
  }

  const parsed = await readBoundedJsonBody(request);
  if (!parsed.ok) {
    return noStoreJson(
      { detail: parsed.status === 413 ? "Request is too large." : "Please provide valid JSON." },
      { status: parsed.status },
    );
  }
  const payload = parsed.value;
  if (
    !payload || typeof payload !== "object" || Array.isArray(payload) ||
    typeof (payload as { token?: unknown }).token !== "string" ||
    (payload as { token: string }).token.length < 32 ||
    (payload as { token: string }).token.length > 256 ||
    typeof (payload as { new_password?: unknown }).new_password !== "string" ||
    (payload as { new_password: string }).new_password.length < 8 ||
    (payload as { new_password: string }).new_password.length > 128
  ) {
    return noStoreJson(
      { detail: "A valid reset token and a password of 8–128 characters are required." },
      { status: 422 },
    );
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/auth/password-reset/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const result = await readBoundedJson(upstream, 16 * 1024);
    return noStoreJson(result ?? { detail: "Unable to reset your password." }, {
      status: upstream.status,
    });
  } catch {
    return noStoreJson(
      { detail: "The MediPredict server is unavailable. Please try again." },
      { status: 503 },
    );
  }
}
