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
const firstSymptomId = catalog.symptoms[0]?.id;
if (typeof firstSymptomId !== "string" || !/^[A-Z0-9_]{2,80}$/.test(firstSymptomId)) {
  throw new Error("Symptom catalog did not provide a valid stable symptom ID");
}

const modelResponse = await request("frontend-to-backend skin model status proxy", "/api/skin-images/model-status", {}, 200);
const model = await modelResponse.json();
if (
  model.inference_available !== false ||
  model.model_configured !== false ||
  model.disease_prediction_performed !== false ||
  model.clinical_validation_status !== "not_established" ||
  model.human_review_required !== true
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
  "frontend-to-backend catalog overlap proxy",
  "/api/symptoms/catalog-match",
  {
    method: "POST",
    headers: { Origin: origin, "Content-Type": "application/json" },
    body: JSON.stringify({ symptom_ids: [firstSymptomId] }),
  },
  200,
);
const match = await matchResponse.json();
if (
  match.method !== "approved_catalog_overlap" ||
  match.clinical_interpretation_performed !== false ||
  match.disease_probability_provided !== false ||
  !Array.isArray(match.results)
) {
  throw new Error("Catalog overlap response violated the non-diagnostic contract");
}

await request(
  "unauthenticated private skin-image intake is rejected",
  "/api/skin-images/intake",
  { method: "POST", headers: { Origin: origin } },
  401,
);

process.stdout.write("Integration smoke checks passed. No personal health data or image was submitted.\n");
