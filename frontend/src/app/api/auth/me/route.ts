import { NextResponse } from "next/server";
import { getSessionUser, SESSION_COOKIE } from "@/lib/auth-proxy";

export async function GET() {
  const result = await getSessionUser();
  if (result.response) return result.response;
  if (!result.user) {
    const response = NextResponse.json(
      { detail: "Your session has expired. Please sign in again." },
      { status: 401, headers: { "Cache-Control": "no-store, max-age=0" } },
    );
    response.cookies.set(SESSION_COOKIE, "", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 0,
    });
    return response;
  }
  return NextResponse.json(
    { user: result.user },
    { headers: { "Cache-Control": "no-store, max-age=0" } },
  );
}