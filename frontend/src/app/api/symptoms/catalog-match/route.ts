import { NextResponse } from "next/server";
import { hasSameRequestOrigin } from "@/lib/request-origin";
import { readBoundedJsonBody } from "@/lib/bounded-json";

const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return NextResponse.json(
      { detail: "Invalid request origin." },
      { status: 403, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }

  const parsed = await readBoundedJsonBody(request, 4_096);
  if (!parsed.ok) {
    return NextResponse.json(
      { detail: parsed.status === 413 ? "Request is too large." : "Please provide valid JSON." },
      { status: parsed.status, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }
  const payload = parsed.value;

  if (
    !payload ||
    typeof payload !== "object" ||
    !("symptom_ids" in payload) ||
    !Array.isArray(payload.symptom_ids) ||
    payload.symptom_ids.length < 1 ||
    payload.symptom_ids.length > 20 ||
    !payload.symptom_ids.every(
      (value) => typeof value === "string" && /^[A-Z0-9_]{2,80}$/.test(value),
    ) ||
    new Set(payload.symptom_ids).size !== payload.symptom_ids.length ||
    Object.keys(payload).sort().join(",") !== "symptom_ids"
  ) {
    return NextResponse.json(
      { detail: "Select between 1 and 20 unique supported symptom identifiers." },
      { status: 422, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/symptoms/catalog-match`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ symptom_ids: payload.symptom_ids }),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    const result = await upstream.json().catch(() => null);
    return NextResponse.json(
      result ?? { detail: "The catalog matching service returned an invalid response." },
      { status: upstream.status, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict API is unavailable. Please try again later." },
      { status: 503, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }
}
