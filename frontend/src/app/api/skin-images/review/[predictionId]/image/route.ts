import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_BASE_URL, SESSION_COOKIE } from "@/lib/auth-proxy";

type RouteContext = { params: Promise<{ predictionId: string }> };

export async function GET(_request: Request, context: RouteContext) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ detail: "Authentication required." }, { status: 401 });
  }

  const { predictionId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(predictionId)) {
    return NextResponse.json({ detail: "Review image not found." }, { status: 404 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_BASE_URL}/skin-images/review/${encodeURIComponent(predictionId)}/image`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(15_000),
      },
    );
  } catch {
    return NextResponse.json({ detail: "Private image service is unavailable." }, { status: 503 });
  }

  if (!upstream.ok) {
    const body = await upstream.json().catch(() => ({ detail: "Review image is unavailable." }));
    return NextResponse.json(body, {
      status: upstream.status,
      headers: { "Cache-Control": "private, no-store" },
    });
  }

  const contentType = upstream.headers.get("content-type");
  if (!contentType || !["image/jpeg", "image/png", "image/webp"].includes(contentType)) {
    return NextResponse.json({ detail: "Unexpected image content type." }, { status: 502 });
  }

  // The backend stores sanitized image objects with an 8 MiB hard limit.
  // Enforce that contract again while proxying; never buffer an unbounded body.
  const maxImageBytes = 8 * 1024 * 1024;
  const declaredLength = upstream.headers.get("content-length");
  if (declaredLength !== null && (!/^\\d+$/.test(declaredLength) || Number(declaredLength) > maxImageBytes)) {
    await upstream.body?.cancel().catch(() => undefined);
    return NextResponse.json({ detail: "Review image exceeds the allowed size." }, { status: 502 });
  }
  if (!upstream.body) {
    return NextResponse.json({ detail: "Review image is empty." }, { status: 502 });
  }

  const reader = upstream.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > maxImageBytes) {
        await reader.cancel();
        return NextResponse.json({ detail: "Review image exceeds the allowed size." }, { status: 502 });
      }
      chunks.push(value);
    }
  } catch {
    await reader.cancel().catch(() => undefined);
    return NextResponse.json({ detail: "Review image could not be retrieved completely." }, { status: 502 });
  }

  const imageBytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    imageBytes.set(chunk, offset);
    offset += chunk.byteLength;
  }

  return new Response(imageBytes, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(totalBytes),
      "Cache-Control": "private, no-store, max-age=0",
      Pragma: "no-cache",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; sandbox",
    },
  });
}
