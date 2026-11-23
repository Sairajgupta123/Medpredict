import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_BASE_URL, SESSION_COOKIE } from "@/lib/auth-proxy";

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const ALLOWED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const EXPECTED_FIELDS = [
  "history_consent",
  "history_policy_version",
  "image",
  "processing_consent",
  "processing_policy_version",
  "review_consent",
  "review_policy_version",
];

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Authentication required." }, { status: 401 });
  }

  let incoming: FormData;
  try {
    incoming = await request.formData();
  } catch {
    return NextResponse.json({ detail: "Please provide a valid image upload." }, { status: 400 });
  }

  const keys = [...new Set(Array.from(incoming.keys()))].sort();
  if (keys.join(",") !== EXPECTED_FIELDS.join(",")) {
    return NextResponse.json({ detail: "The upload form is incomplete or contains unexpected fields." }, { status: 422 });
  }

  const image = incoming.get("image");
  if (!(image instanceof File) || image.size === 0) {
    return NextResponse.json({ detail: "Choose a JPEG, PNG or WebP image." }, { status: 422 });
  }
  if (image.size > MAX_IMAGE_BYTES) {
    return NextResponse.json({ detail: "Image exceeds the 8 MiB upload limit." }, { status: 413 });
  }
  if (!ALLOWED_TYPES.has(image.type)) {
    return NextResponse.json({ detail: "Only JPEG, PNG and WebP images are supported." }, { status: 422 });
  }

  for (const field of ["processing_consent", "history_consent", "review_consent"]) {
    if (incoming.get(field) !== "true") {
      return NextResponse.json({ detail: "All three separate consent choices are required." }, { status: 422 });
    }
  }
  for (const field of ["processing_policy_version", "history_policy_version", "review_policy_version"]) {
    const value = incoming.get(field);
    if (typeof value !== "string" || value.length < 1 || value.length > 40 || value.trim() !== value) {
      return NextResponse.json({ detail: "A valid consent policy version is required." }, { status: 422 });
    }
  }

  const forwarded = new FormData();
  for (const field of EXPECTED_FIELDS) {
    const value = incoming.get(field);
    if (value instanceof File) forwarded.append(field, value, value.name);
    else if (typeof value === "string") forwarded.append(field, value);
  }

  try {
    const upstream = await fetch(`${API_BASE_URL}/skin-images/intake`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      body: forwarded,
      cache: "no-store",
    });
    const body = await upstream.json().catch(() => null);
    return NextResponse.json(
      body ?? { detail: "The image service returned an invalid response." },
      { status: upstream.status, headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return NextResponse.json(
      { detail: "The private image service is unavailable. Your image was not confirmed as stored." },
      { status: 503 },
    );
  }
}
