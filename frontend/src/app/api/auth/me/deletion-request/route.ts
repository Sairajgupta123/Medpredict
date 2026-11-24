import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_BASE_URL, SESSION_COOKIE, readBoundedJson } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";

function privateJson(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "private, no-store, max-age=0", Pragma: "no-cache" },
  });
}

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return privateJson({ detail: "Invalid request origin." }, 403);
  }

  const declaredLength = request.headers.get("content-length");
  if (declaredLength && (!/^\d+$/.test(declaredLength) || Number(declaredLength) > 8_192)) {
    return privateJson({ detail: "The request is too large." }, 413);
  }

  let raw = "";
  const reader = request.body?.getReader();
  if (!reader) return privateJson({ detail: "Please provide a valid request." }, 400);
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      raw += decoder.decode(value, { stream: true });
      if (new TextEncoder().encode(raw).byteLength > 8_192) {
        await reader.cancel();
        return privateJson({ detail: "The request is too large." }, 413);
      }
    }
    raw += decoder.decode();
  } catch {
    await reader.cancel().catch(() => undefined);
    return privateJson({ detail: "Please provide a valid request." }, 400);
  }

  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return privateJson({ detail: "Please provide valid JSON." }, 400);
  }
  if (
    !payload || typeof payload !== "object" || Array.isArray(payload) ||
    !("password" in payload) || typeof payload.password !== "string" ||
    payload.password.length < 1 || payload.password.length > 128
  ) {
    return privateJson({ detail: "Please enter your current password." }, 422);
  }

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return privateJson({ detail: "Your session has expired. Please sign in again." }, 401);

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/auth/me/deletion-request`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ password: payload.password }),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    return privateJson({ detail: "The MediPredict server is unavailable. Please try again." }, 503);
  }

  const result = await readBoundedJson(upstream, 16 * 1024);\n  if (result === null) {\n    return privateJson({ detail: "The deletion service returned an invalid response." }, 502);\n  }
  if (!upstream.ok) {
    const detail = result && typeof result === "object" && "detail" in result
      ? result.detail : "The deletion request could not be submitted.";
    return privateJson({ detail }, upstream.status);
  }

  const response = privateJson(result, upstream.status);
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
