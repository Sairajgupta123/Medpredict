import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

export async function GET() {
  try {
    const upstream = await fetch(`${API_BASE_URL}/symptoms/catalog`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const result = await upstream.json().catch(() => null);
    return NextResponse.json(
      result ?? { detail: "The symptom catalogue returned an invalid response." },
      {
        status: upstream.status,
        headers: { "Cache-Control": "no-store, max-age=0" },
      },
    );
  } catch {
    return NextResponse.json(
      { detail: "The symptom catalogue is unavailable. Please try again later." },
      { status: 503, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }
}
