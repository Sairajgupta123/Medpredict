import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_BASE_URL, SESSION_COOKIE, readBoundedJson } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";

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

function privateJson(body: unknown, init: ResponseInit = {}) {
  return NextResponse.json(body, {
    ...init,
    headers: {
      ...init.headers,
      "Cache-Control": "private, no-store, max-age=0",
    },
  });
}


export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return privateJson({ detail: "Invalid request origin." }, { status: 403 });
  }

  const maxRequestBytes = MAX_IMAGE_BYTES + 64 * 1024;
  const declaredLengthHeader = request.headers.get("content-length");
  if (declaredLengthHeader !== null) {
    if (!/^\d+$/.test(declaredLengthHeader)) {
      return privateJson({ detail: "Invalid upload request size." }, { status: 400 });
    }
    if (Number(declaredLengthHeader) > maxRequestBytes) {
      return privateJson({ detail: "Image upload exceeds the permitted request size." }, { status: 413 });
    }
  }

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return privateJson({ detail: "Authentication required." }, { status: 401 });
  }

  let incoming: FormData;
  try {
    // Do not trust Content-Length: chunked or proxied requests may omit it.
    // Bound the actual stream before parsing multipart data into memory.
    if (!request.body) {
      return privateJson({ detail: "Please provide a valid image upload." }, { status: 400 });
    }
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let receivedBytes = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        receivedBytes += value.byteLength;
        if (receivedBytes > maxRequestBytes) {
          await reader.cancel();
          return privateJson(
            { detail: "Image upload exceeds the permitted request size." },
            { status: 413 },
          );
        }
        chunks.push(new Uint8Array(value));
      }
    } finally {
      reader.releaseLock();
    }
    const contentType = request.headers.get("content-type");
    if (!contentType?.toLowerCase().startsWith("multipart/form-data;")) {
      return privateJson({ detail: "Please provide a valid image upload." }, { status: 400 });
    }
    incoming = await new Response(new Blob(chunks), {
      headers: { "Content-Type": contentType },
    }).formData();
  } catch {
    return privateJson({ detail: "Please provide a valid image upload." }, { status: 400 });
  }

  const incomingKeys = Array.from(incoming.keys());
  const keys = [...new Set(incomingKeys)].sort();
  if (incomingKeys.length !== EXPECTED_FIELDS.length || keys.join(",") !== EXPECTED_FIELDS.join(",")) {
    return privateJson({ detail: "The upload form is incomplete or contains unexpected fields." }, { status: 422 });
  }

  const image = incoming.get("image");
  if (!(image instanceof File) || image.size === 0) {
    return privateJson({ detail: "Choose a JPEG, PNG or WebP image." }, { status: 422 });
  }
  if (image.size > MAX_IMAGE_BYTES) {
    return privateJson({ detail: "Image exceeds the 8 MiB upload limit." }, { status: 413 });
  }
  if (!ALLOWED_TYPES.has(image.type)) {
    return privateJson({ detail: "Only JPEG, PNG and WebP images are supported." }, { status: 422 });
  }

  for (const field of ["processing_consent", "history_consent", "review_consent"]) {
    if (incoming.get(field) !== "true") {
      return privateJson({ detail: "All three separate consent choices are required." }, { status: 422 });
    }
  }
  for (const field of ["processing_policy_version", "history_policy_version", "review_policy_version"]) {
    const value = incoming.get(field);
    if (typeof value !== "string" || value.length < 1 || value.length > 40 || value.trim() !== value) {
      return privateJson({ detail: "A valid consent policy version is required." }, { status: 422 });
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
      signal: AbortSignal.timeout(30_000),
    });
    const body = await readBoundedJson(upstream, 32 * 1024);
    return privateJson(
      body ?? { detail: "The image service returned an invalid response." },
      { status: upstream.status, headers: { "Cache-Control": "private, no-store" } },
    );
  } catch {
    return privateJson(
      { detail: "The private image service is unavailable. Your image was not confirmed as stored." },
      { status: 503 },
    );
  }
}
