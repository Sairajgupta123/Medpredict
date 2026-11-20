import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth-proxy";

const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

function noStore(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "no-store, max-age=0" },
  });
}

async function sessionToken() {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

export async function GET(request: Request) {
  const token = await sessionToken();
  if (!token) return noStore({ detail: "Please sign in to access the review queue." }, 401);

  const incoming = new URL(request.url);
  const upstreamUrl = new URL(`${API_BASE_URL}/catalog/review/queue`);
  for (const key of ["target_type", "status", "limit"]) {
    for (const value of incoming.searchParams.getAll(key)) {
      upstreamUrl.searchParams.append(key, value);
    }
  }

  try {
    const upstream = await fetch(upstreamUrl, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    const result = await upstream.json().catch(() => null);
    return noStore(result ?? { detail: "The review service returned an invalid response." }, upstream.status);
  } catch {
    return noStore({ detail: "The review service is unavailable. Please try again." }, 503);
  }
}

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return noStore({ detail: "Invalid request origin." }, 403);
  }

  const token = await sessionToken();
  if (!token) return noStore({ detail: "Please sign in to continue." }, 401);

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return noStore({ detail: "Please provide valid JSON." }, 400);
  }

  if (!payload || typeof payload !== "object") {
    return noStore({ detail: "Invalid review request." }, 422);
  }

  const value = payload as Record<string, unknown>;
  const targetType = value.target_type;
  const targetKey = typeof value.target_key === "string" ? value.target_key.trim() : "";
  const status = value.status;
  const reason = typeof value.reason === "string" ? value.reason.trim() : "";

  if (
    !["disease", "symptom", "disease_symptom"].includes(String(targetType)) ||
    !targetKey ||
    targetKey.length > 200 ||
    !["draft", "in_review", "approved", "retired"].includes(String(status)) ||
    reason.length < 8 ||
    reason.length > 1000
  ) {
    return noStore({ detail: "Check the review item, status and reason (8–1,000 characters)." }, 422);
  }

  let endpoint: string;
  if (targetType === "disease") {
    endpoint = `/catalog/review/diseases/${encodeURIComponent(targetKey)}`;
  } else if (targetType === "symptom") {
    endpoint = `/catalog/review/symptoms/${encodeURIComponent(targetKey)}`;
  } else {
    const separator = targetKey.indexOf(":");
    if (separator < 1 || separator === targetKey.length - 1) {
      return noStore({ detail: "The disease-symptom key is invalid." }, 422);
    }
    const diseaseCode = targetKey.slice(0, separator);
    const symptomCode = targetKey.slice(separator + 1);
    endpoint = `/catalog/review/diseases/${encodeURIComponent(diseaseCode)}/symptoms/${encodeURIComponent(symptomCode)}`;
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ status, reason }),
      cache: "no-store",
    });
    const result = await upstream.json().catch(() => null);
    return noStore(result ?? { detail: "The review service returned an invalid response." }, upstream.status);
  } catch {
    return noStore({ detail: "The review service is unavailable. Please try again." }, 503);
  }
}
