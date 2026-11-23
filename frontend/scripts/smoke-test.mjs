const baseUrl = process.env.SMOKE_BASE_URL ?? "http://localhost:3000";

async function check(name, request, expectedStatus, expectedCacheControl = true) {
  const response = await fetch(new URL(request.path, baseUrl), request.init);
  if (response.status !== expectedStatus) {
    throw new Error(`${name}: expected HTTP ${expectedStatus}, received ${response.status}`);
  }
  if (expectedCacheControl) {
    const cacheControl = response.headers.get("cache-control") ?? "";
    if (!cacheControl.includes("no-store")) {
      throw new Error(`${name}: expected a no-store response, received "${cacheControl}"`);
    }
  }
  process.stdout.write(`PASS ${name} (HTTP ${response.status})\n`);
}

const home = await fetch(baseUrl);
if (!home.ok) throw new Error(`Homepage returned HTTP ${home.status}`);
process.stdout.write(`PASS production homepage (HTTP ${home.status})\n`);

const path = "/api/symptoms/normalize";
await check(
  "reject cross-origin symptom request",
  { path, init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: "{}" } },
  403,
);
await check(
  "reject malformed JSON",
  { path, init: { method: "POST", headers: { Origin: baseUrl, "Content-Type": "application/json" }, body: "{" } },
  400,
);
await check(
  "reject invalid symptom payload",
  { path, init: { method: "POST", headers: { Origin: baseUrl, "Content-Type": "application/json" }, body: JSON.stringify({ text: " ", reported_context: {} }) } },
  422,
);

const catalogPath = "/api/symptoms/catalog";
await check(
  "reject cross-origin catalog-match request",
  { path: "/api/symptoms/catalog-match", init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: JSON.stringify({ symptom_ids: ["HEADACHE"] }) } },
  403,
);
process.stdout.write("Production smoke checks completed. No personal health data was submitted.\n");
