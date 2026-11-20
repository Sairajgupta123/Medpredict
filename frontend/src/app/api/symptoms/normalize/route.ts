import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Please provide valid JSON." }, { status: 400 });
  }

  if (
    !payload ||
    typeof payload !== "object" ||
    !("text" in payload) ||
    typeof payload.text !== "string" ||
    payload.text.trim().length === 0 ||
    payload.text.length > 4000
  ) {
    return NextResponse.json(
      { detail: "Enter symptom text between 1 and 4,000 characters." },
      { status: 422 },
    );
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/symptoms/normalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ text: payload.text }),
      cache: "no-store",
    });
    const result = await upstream.json().catch(() => null);
    return NextResponse.json(
      result ?? { detail: "The symptom service returned an invalid response." },
      { status: upstream.status },
    );
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict API is unavailable. Please try again later." },
      { status: 503 },
    );
  }
}
