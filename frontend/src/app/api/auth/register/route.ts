import { proxyCredentials } from "@/lib/auth-proxy";

export async function POST(request: Request) {
  return proxyCredentials(request, "register");
}
