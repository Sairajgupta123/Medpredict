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

  return new Response(await upstream.arrayBuffer(), {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "private, no-store, max-age=0",
      Pragma: "no-cache",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; sandbox",
    },
  });
}
