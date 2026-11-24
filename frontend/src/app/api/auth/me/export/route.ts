import { NextResponse } from "next/server";
import { API_BASE_URL, getSessionToken } from "@/lib/auth-proxy";

export async function GET() {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json(
      { detail: "Your session has expired. Please sign in again." },
      { status: 401, headers: { "Cache-Control": "private, no-store, max-age=0" } },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/auth/me/export`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict server is unavailable. Please try again shortly." },
      { status: 503, headers: { "Cache-Control": "private, no-store, max-age=0" } },
    );
  }

  const body = await upstream.json().catch(() => null);
  if (!upstream.ok) {
    return NextResponse.json(
      body ?? { detail: "The account export could not be generated." },
      { status: upstream.status, headers: { "Cache-Control": "private, no-store, max-age=0" } },
    );
  }

  return new NextResponse(JSON.stringify(body), {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": 'attachment; filename="medipredict-account-export.json"',
      "Cache-Control": "private, no-store, max-age=0",
      Pragma: "no-cache",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
