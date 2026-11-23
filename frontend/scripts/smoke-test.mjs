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
const requestOrigin = new URL(home.url).origin;
process.stdout.write(`PASS production homepage (HTTP ${home.status})\n`);



for (const endpoint of ["login", "register"]) {
  const authPath = `/api/auth/${endpoint}`;
  await check(
    `reject cross-origin auth ${endpoint}`,
    { path: authPath, init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: "{}" } },
    403,
  );
  await check(
    `reject malformed auth ${endpoint} payload`,
    { path: authPath, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: "{" } },
    400,
  );
  await check(
    `reject oversized auth ${endpoint} payload`,
    { path: authPath, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: "x".repeat(32 * 1024 + 1) } },
    413,
  );
}

const logoutPath = "/api/auth/logout";
await check(
  "reject cross-origin logout request",
  { path: logoutPath, init: { method: "POST", headers: { Origin: "https://invalid.example" } } },
  403,
);
await check(
  "allow same-origin logout and clear session",
  { path: logoutPath, init: { method: "POST", headers: { Origin: requestOrigin } } },
  200,
);

const path = "/api/symptoms/normalize";
await check(
  "reject cross-origin symptom request",
  { path, init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: "{}" } },
  403,
);
await check(
  "reject malformed JSON",
  { path, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: "{" } },
  400,
);
await check(
  "reject invalid symptom payload",
  { path, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: JSON.stringify({ text: " ", reported_context: {} }) } },
  422,
);

const catalogPath = "/api/symptoms/catalog";
await check(
  "reject cross-origin catalog-match request",
  { path: "/api/symptoms/catalog-match", init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: JSON.stringify({ symptom_ids: ["HEADACHE"] }) } },
  403,
);

const skinIntakePath = "/api/skin-images/intake";
await check(
  "reject cross-origin skin-image upload",
  { path: skinIntakePath, init: { method: "POST", headers: { Origin: "https://invalid.example" } } },
  403,
);
await check(
  "require authentication before skin-image upload parsing",
  { path: skinIntakePath, init: { method: "POST", headers: { Origin: requestOrigin } } },
  401,
);


const testPredictionId = "00000000-0000-4000-8000-000000000001";
await check(
  "require authentication to revoke skin-image review consent",
  { path: `/api/skin-images/${testPredictionId}/revoke-review-consent`, init: { method: "POST", headers: { Origin: requestOrigin } } },
  401,
);
await check(
  "require authentication to retrieve private skin review image",
  { path: `/api/skin-images/review/${testPredictionId}/image`, init: { method: "GET" } },
  401,
);

process.stdout.write("Production smoke checks completed. No personal health data was submitted.\n");
