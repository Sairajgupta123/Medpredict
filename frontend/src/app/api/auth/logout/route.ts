import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";

function privateJson(body: unknown, init: ResponseInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Cache-Control", "private, no-store, max-age=0");
  headers.set("Pragma", "no-cache");
  return NextResponse.json(body, { ...init, headers });
}

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return privateJson({ detail: "Invalid request origin." }, { status: 403 });
  }

  const response = privateJson({ message: "Signed out successfully." });
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
