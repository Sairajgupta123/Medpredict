import { NextResponse } from "next/server";
import { API_BASE_URL } from "@/lib/auth-proxy";

export async function GET() {
  try {
    const upstream = await fetch(`${API_BASE_URL}/skin-images/model-status`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await upstream.json().catch(() => null);
    return NextResponse.json(
      payload ?? { detail: "The skin-image capability service returned an invalid response." },
      {
        status: upstream.status,
        headers: { "Cache-Control": "private, no-store, max-age=0" },
      },
    );
  } catch {
    return NextResponse.json(
      { detail: "Skin-image model availability could not be checked." },
      { status: 503, headers: { "Cache-Control": "private, no-store, max-age=0" } },
    );
  }
}
