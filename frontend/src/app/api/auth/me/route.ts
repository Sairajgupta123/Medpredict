import { NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth-proxy";

export async function GET() {
  const result = await getSessionUser();
  if (result.response) return result.response;
  if (!result.user) {
    return NextResponse.json({ detail: "Your session has expired. Please sign in again." }, { status: 401 });
  }
  return NextResponse.json({ user: result.user });
}
