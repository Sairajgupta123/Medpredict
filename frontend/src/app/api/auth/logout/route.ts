import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth-proxy";
import { hasSameRequestOrigin } from "@/lib/request-origin";

export async function POST(request: Request) {
  if (!hasSameRequestOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  const response = NextResponse.json({ message: "Signed out successfully." });
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
