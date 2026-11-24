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
  return response;
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
    `reject missing auth ${endpoint} origin`,
    { path: authPath, init: { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" } },
    403,
  );
  await check(
    `reject malformed auth ${endpoint} origin`,
    { path: authPath, init: { method: "POST", headers: { Origin: "not-an-origin", "Content-Type": "application/json" }, body: "{}" } },
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

for (const action of ["request", "confirm"]) {
  const verificationPath = `/api/auth/email-verification/${action}`;
  await check(
    `reject cross-origin email verification ${action}`,
    { path: verificationPath, init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: "{}" } },
    403,
  );
  await check(
    `reject missing origin for email verification ${action}`,
    { path: verificationPath, init: { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" } },
    403,
  );
  await check(
    `reject malformed email verification ${action} payload`,
    { path: verificationPath, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: "{" } },
    400,
  );
}

for (const action of ["request", "confirm"]) {
  const resetPath = `/api/auth/password-reset/${action}`;
  await check(
    `reject cross-origin password reset ${action}`,
    { path: resetPath, init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: "{}" } },
    403,
  );
  await check(
    `reject missing origin for password reset ${action}`,
    { path: resetPath, init: { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" } },
    403,
  );
  await check(
    `reject malformed password reset ${action} payload`,
    { path: resetPath, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: "{" } },
    400,
  );
}
await check(
  "reject invalid password reset confirmation fields",
  { path: "/api/auth/password-reset/confirm", init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: JSON.stringify({ token: "short", new_password: "short" }) } },
  422,
);

const logoutPath = "/api/auth/logout";
await check(
  "reject cross-origin logout request",
  { path: logoutPath, init: { method: "POST", headers: { Origin: "https://invalid.example" } } },
  403,
);
const logoutResponse = await check(
  "allow same-origin logout and clear session",
  { path: logoutPath, init: { method: "POST", headers: { Origin: requestOrigin } } },
  200,
);
const clearedCookie = logoutResponse.headers.get("set-cookie") ?? "";
for (const attribute of ["HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=0"]) {
  if (!clearedCookie.toLowerCase().includes(attribute.toLowerCase())) {
    throw new Error(`logout cookie: expected ${attribute} in "${clearedCookie}"`);
  }
}
process.stdout.write("PASS logout clears the session with secure cookie attributes\n");

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
  "reject oversized symptom request body",
  { path, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: JSON.stringify({ text: "x".repeat(8 * 1024), reported_context: { duration: "not_sure", severity: "not_sure", onset: "not_sure" } }) } },
  413,
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
await check(
  "reject oversized catalog-match request body",
  { path: "/api/symptoms/catalog-match", init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: JSON.stringify({ symptom_ids: ["A".repeat(4 * 1024)] }) } },
  413,
);
await check(
  "reject malformed catalog-match identifiers",
  { path: "/api/symptoms/catalog-match", init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: JSON.stringify({ symptom_ids: ["not-a-valid-id"] }) } },
  422,
);
await check(
  "reject duplicate catalog-match identifiers",
  { path: "/api/symptoms/catalog-match", init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: JSON.stringify({ symptom_ids: ["HEADACHE", "HEADACHE"] }) } },
  422,
);
await check(
  "return controlled unavailable response for symptom catalog",
  { path: "/api/symptoms/catalog", init: { method: "GET" } },
  503,
);
await check(
  "return controlled unavailable response for skin model status",
  { path: "/api/skin-images/model-status", init: { method: "GET" } },
  503,
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
await check(
  "reject oversized skin-image upload before parsing",
  { path: skinIntakePath, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/octet-stream" }, body: "x".repeat(8 * 1024 * 1024 + 64 * 1024 + 1) } },
  413,
);


const deletionRequestPath = "/api/auth/me/deletion-request";
await check(
  "reject cross-origin account deletion request",
  { path: deletionRequestPath, init: { method: "POST", headers: { Origin: "https://invalid.example", "Content-Type": "application/json" }, body: JSON.stringify({ password: "SmokeTestPassword123!" }) } },
  403,
);
await check(
  "require authentication for account deletion request",
  { path: deletionRequestPath, init: { method: "POST", headers: { Origin: requestOrigin, "Content-Type": "application/json" }, body: JSON.stringify({ password: "SmokeTestPassword123!" }) } },
  401,
);
await check(
  "require authentication for private account export",
  { path: "/api/auth/me/export", init: { method: "GET" } },
  401,
);

const testPredictionId = "00000000-0000-4000-8000-000000000001";
await check(
  "reject cross-origin skin-image review consent revocation",
  { path: `/api/skin-images/${testPredictionId}/revoke-review-consent`, init: { method: "POST", headers: { Origin: "https://invalid.example" } } },
  403,
);
await check(
  "reject missing origin for skin-image review consent revocation",
  { path: `/api/skin-images/${testPredictionId}/revoke-review-consent`, init: { method: "POST" } },
  403,
);
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
