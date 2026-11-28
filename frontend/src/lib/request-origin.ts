/**
 * Validate browser Origin against the externally visible request host.
 * Next.js may construct request.url from an internal proxy address, so use
 * the Host header and the trusted proxy's forwarded protocol when present.
 */
export function hasSameRequestOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return false;

  try {
    const parsedOrigin = new URL(origin);
    if (
      parsedOrigin.username ||
      parsedOrigin.password ||
      parsedOrigin.pathname !== "/" ||
      parsedOrigin.search ||
      parsedOrigin.hash
    ) return false;

    const forwardedProtocolHeader = request.headers.get("x-forwarded-proto");
    const protocol = forwardedProtocolHeader === null
      ? new URL(request.url).protocol.replace(/:$/, "")
      : forwardedProtocolHeader.trim().toLowerCase();
    if (protocol !== "http" && protocol !== "https") return false;

    return parsedOrigin.host.toLowerCase() === host.toLowerCase() &&
      parsedOrigin.protocol === `${protocol}:`;
  } catch {
    return false;
  }
}
