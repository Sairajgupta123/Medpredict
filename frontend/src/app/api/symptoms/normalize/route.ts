import { NextResponse } from "next/server";

const API_BASE_URL =
  process.env.MEDIPREDICT_API_INTERNAL_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000/api/v1";

const allowedValues = {
  duration: ["less_than_24_hours", "one_to_three_days", "four_to_seven_days", "more_than_one_week", "not_sure"],
  severity: ["mild", "moderate", "severe", "not_sure"],
  onset: ["sudden", "gradual", "comes_and_goes", "not_sure"],
};

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return NextResponse.json(
      { detail: "Invalid request origin." },
      { status: 403, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Please provide valid JSON." },
      { status: 400, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }

  if (
    !payload ||
    typeof payload !== "object" ||
    !("text" in payload) ||
    typeof payload.text !== "string" ||
    payload.text.trim().length === 0 ||
    payload.text.length > 4000 ||
    !("reported_context" in payload) ||
    !payload.reported_context ||
    typeof payload.reported_context !== "object"
  ) {
    return NextResponse.json(
      { detail: "Enter symptom text and select valid symptom context." },
      { status: 422, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }

  const context = payload.reported_context as Record<string, unknown>;
  const validContext = Object.entries(allowedValues).every(
    ([key, values]) => typeof context[key] === "string" && values.includes(context[key] as string),
  );
  const exactContextKeys = Object.keys(context).sort().join(",") === "duration,onset,severity";

  if (!validContext || !exactContextKeys) {
    return NextResponse.json(
      { detail: "The duration, severity or onset selection is invalid." },
      { status: 422, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/symptoms/normalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        text: payload.text,
        reported_context: context,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    const result = await upstream.json().catch(() => null);
    return NextResponse.json(
      result ?? { detail: "The symptom service returned an invalid response." },
      { status: upstream.status, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  } catch {
    return NextResponse.json(
      { detail: "The MediPredict API is unavailable. Please try again later." },
      { status: 503, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
  }
}
