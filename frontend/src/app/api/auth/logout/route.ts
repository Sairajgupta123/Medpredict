import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_BASE_URL, SESSION_COOKIE } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";

function privateJson(body: unknown, init: ResponseInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Cache-Control", "private, no-store, max-age=0");
  headers.set("Pragma", "no-cache");
  return NextResponse.json(body, { ...init, headers });
}

function clearSessionCookie(response: NextResponse) {
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return privateJson({ detail: "Invalid request origin." }, { status: 403 });
  }

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (token) {
    try {
      const backendResponse = await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/json",
        },
        cache: "no-store",
        signal: AbortSignal.timeout(8_000),
      });

      // A 401 means the token is already invalid/revoked. For transient
      // backend failures, keep the browser cookie so the user can retry.
      if (!backendResponse.ok && backendResponse.status !== 401) {
        return privateJson(
          { detail: "The session could not be revoked. Please try again." },
          { status: 503 },
        );
      }
    } catch {
      return privateJson(
        { detail: "The MediPredict server is unavailable. Please try again." },
        { status: 503 },
      );
    }
  }

  return clearSessionCookie(
    privateJson({ message: "Signed out successfully." }),
  );
}
