const baseUrl = process.env.SMOKE_BASE_URL ?? "http://localhost:3000";

async function request(name, path, init, expectedStatus) {
  const response = await fetch(new URL(path, baseUrl), init);
  if (response.status !== expectedStatus) {
    const body = await response.text();
    throw new Error(`${name}: expected HTTP ${expectedStatus}, received ${response.status}: ${body.slice(0, 500)}`);
  }
  const cacheControl = response.headers.get("cache-control") ?? "";
  if (!cacheControl.includes("no-store")) {
    throw new Error(`${name}: response must not be cached (Cache-Control: ${cacheControl})`);
  }
  process.stdout.write(`PASS ${name} (HTTP ${response.status})\n`);
  return response;
}

const home = await fetch(baseUrl);
if (!home.ok) throw new Error(`Frontend homepage returned HTTP ${home.status}`);
const origin = new URL(home.url).origin;
process.stdout.write("PASS frontend production server\n");

const health = await fetch("http://127.0.0.1:8000/api/v1/health");
if (!health.ok || (await health.json()).status !== "ok") {
  throw new Error("Backend liveness check failed");
}
const ready = await fetch("http://127.0.0.1:8000/api/v1/health/ready");
if (!ready.ok || (await ready.json()).status !== "ready") {
  throw new Error("Backend database readiness check failed");
}
process.stdout.write("PASS backend liveness and PostgreSQL readiness\n");

const catalogResponse = await request("frontend-to-backend symptom catalog proxy", "/api/symptoms/catalog", {}, 200);
const catalog = await catalogResponse.json();
if (
  !catalog ||
  typeof catalog.taxonomy_version !== "string" ||
  !Array.isArray(catalog.symptoms) ||
  catalog.clinical_interpretation_performed !== false ||
  catalog.symptoms.length === 0
) {
  throw new Error("Symptom catalog response did not match the safe API contract");
}
// The phrase taxonomy IDs are intentionally distinct from clinician-approved
// database catalog codes. The CI database has no reviewed clinical catalog seed,
// so assert that an unknown, well-formed code is rejected rather than treating
// a research taxonomy ID as an approved clinical catalog entry.
const unknownCatalogCode = "SMOKE_TEST_UNAPPROVED";


const modelResponse = await request("frontend-to-backend skin model status proxy", "/api/skin-images/model-status", {}, 200);
const model = await modelResponse.json();
if (
  model.inference_available !== false ||
  model.model_configured !== false ||
  model.disease_prediction_performed !== false ||
  model.clinical_validation_status !== "not_established" ||
  model.human_review_required !== true ||
  model.image_intake_configured !== false ||
  model.image_retention_days !== null
) {
  throw new Error("Skin model status did not preserve the disabled/non-clinical capability contract");
}

const normalizeResponse = await request(
  "frontend-to-backend symptom normalization proxy",
  "/api/symptoms/normalize",
  {
    method: "POST",
    headers: { Origin: origin, "Content-Type": "application/json" },
    body: JSON.stringify({
      text: "headache",
      reported_context: {
        duration: "not_sure",
        severity: "not_sure",
        onset: "not_sure",
      },
    }),
  },
  200,
);
const normalized = await normalizeResponse.json();
if (
  normalized.research_only !== true ||
  normalized.clinical_interpretation_performed !== false ||
  normalized.model_inference_performed !== false ||
  normalized.disease_prediction_performed !== false ||
  !Array.isArray(normalized.matched_symptoms)
) {
  throw new Error("Symptom normalization response violated the non-diagnostic contract");
}

const matchResponse = await request(
  "frontend-to-backend catalog rejects unapproved symptom code",
  "/api/symptoms/catalog-match",
  {
    method: "POST",
    headers: { Origin: origin, "Content-Type": "application/json" },
    body: JSON.stringify({ symptom_ids: [unknownCatalogCode] }),
  },
  422,
);
const matchError = await matchResponse.json();
if (matchError.detail !== "One or more symptom IDs are not in the approved catalog.") {
  throw new Error("Catalog matching did not reject an unapproved symptom code safely");
}


await request(
  "unauthenticated private skin-image intake is rejected",
  "/api/skin-images/intake",
  { method: "POST", headers: { Origin: origin } },
  401,
);

process.stdout.write("Integration smoke checks passed. No personal health data or image was submitted.\n");
