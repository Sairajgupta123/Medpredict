"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";

type IntakeResponse = {
  prediction_id: string;
  status: "review_required";
  storage_status: "stored";
  quality_warnings: string[];
  message: string;
};

type ApiError = { detail?: string };

type ModelStatus = {
  inference_available: boolean;
  model_configured: boolean;
  disease_prediction_performed: boolean;
  clinical_validation_status: string;
  human_review_required: boolean;
  message: string;
};

const POLICY_VERSIONS = {
  processing: "image-processing-v1",
  history: "image-history-v1",
  review: "image-review-v1",
};

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];

export function SkinImageIntake() {
  const [image, setImage] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [processingConsent, setProcessingConsent] = useState(false);
  const [historyConsent, setHistoryConsent] = useState(false);
  const [reviewConsent, setReviewConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<IntakeResponse | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revocationMessage, setRevocationMessage] = useState("");

  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [modelStatusUnavailable, setModelStatusUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    fetch("/api/skin-images/model-status", {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Status unavailable");
        const payload = await response.json() as Partial<ModelStatus>;
        if (
          typeof payload.inference_available !== "boolean" ||
          typeof payload.model_configured !== "boolean" ||
          typeof payload.disease_prediction_performed !== "boolean" ||
          typeof payload.clinical_validation_status !== "string" ||
          payload.human_review_required !== true ||
          payload.disease_prediction_performed !== false ||
          (payload.inference_available && !payload.model_configured) ||
          typeof payload.message !== "string"
        ) throw new Error("Invalid or unsafe status response");
        if (active) setModelStatus(payload as ModelStatus);
      })
      .catch(() => {
        if (active) setModelStatusUnavailable(true);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!image) {
      setPreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(image);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setError("");
    setResult(null);
    setRevocationMessage("");
    if (!selected) {
      setImage(null);
      return;
    }
    if (!ACCEPTED_TYPES.includes(selected.type)) {
      setImage(null);
      event.target.value = "";
      setError("Choose a JPEG, PNG or WebP image.");
      return;
    }
    if (selected.size > MAX_IMAGE_BYTES) {
      setImage(null);
      event.target.value = "";
      setError("The image must be 8 MiB or smaller.");
      return;
    }
    setImage(selected);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setResult(null);
    setRevocationMessage("");
    if (!image) {
      setError("Choose an image before continuing.");
      return;
    }
    if (!processingConsent || !historyConsent || !reviewConsent) {
      setError("Please review and select all three separate consent choices.");
      return;
    }

    const body = new FormData();
    body.append("image", image, image.name);
    body.append("processing_consent", "true");
    body.append("history_consent", "true");
    body.append("review_consent", "true");
    body.append("processing_policy_version", POLICY_VERSIONS.processing);
    body.append("history_policy_version", POLICY_VERSIONS.history);
    body.append("review_policy_version", POLICY_VERSIONS.review);

    setSubmitting(true);
    try {
      const response = await fetch("/api/skin-images/intake", {
        method: "POST",
        body,
        cache: "no-store",
        // The server-side proxy allows 30 seconds for the private storage service.
        // Keep the browser request slightly longer so it can receive that response.
        signal: AbortSignal.timeout(35_000),
      });
      const payload = await response.json() as IntakeResponse & ApiError;
      if (!response.ok) {
        setError(payload.detail ?? "The image could not be securely received.");
        return;
      }
      const validPredictionId =
        typeof payload.prediction_id === "string" &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(payload.prediction_id);
      const allowedWarnings = new Set([
        "low_resolution",
        "possibly_too_dark",
        "possibly_overexposed",
        "low_contrast_or_uniform_image",
      ]);
      const validWarnings =
        Array.isArray(payload.quality_warnings) &&
        payload.quality_warnings.every(
          (warning): warning is string =>
            typeof warning === "string" && allowedWarnings.has(warning),
        );
      if (
        payload.status !== "review_required" ||
        payload.storage_status !== "stored" ||
        !validPredictionId ||
        !validWarnings ||
        typeof payload.message !== "string" ||
        payload.message.trim().length === 0
      ) {
        setError("The server returned an unexpected response. Storage was not confirmed.");
        return;
      }
      setResult(payload);
      setImage(null);
      setProcessingConsent(false);
      setHistoryConsent(false);
      setReviewConsent(false);
    } catch {
      setError("Unable to reach the private image service. Storage was not confirmed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function revokeReviewConsent() {
    if (!result) return;
    setRevoking(true);
    setError("");
    setRevocationMessage("");
    try {
      const response = await fetch(
        `/api/skin-images/${encodeURIComponent(result.prediction_id)}/revoke-review-consent`,
        { method: "POST", cache: "no-store", signal: AbortSignal.timeout(10_000) },
      );
      const payload = await response.json() as ApiError & { consent_status?: string; reviewer_access_revoked?: boolean };
      if (!response.ok || payload.consent_status !== "revoked" || payload.reviewer_access_revoked !== true) {
        setError(payload.detail ?? "Review consent revocation could not be confirmed.");
        return;
      }
      setRevocationMessage("Human-review consent is revoked. Reviewer access for this image has been disabled.");
    } catch {
      setError("The consent service is unavailable. Review revocation was not confirmed.");
    } finally {
      setRevoking(false);
    }
  }

  return (
    <div className="skin-intake-workspace">
      <section className="skin-intake-model-status" aria-live="polite" aria-label="Image model availability">
        <strong>Image classification status</strong>
        {modelStatus ? (
          <>
            <p>{modelStatus.message}</p>
            <ul>
              <li>{modelStatus.inference_available && modelStatus.model_configured ? "Model inference available" : "Disease classification is not currently available"}</li>
              <li>{modelStatus.clinical_validation_status === "not_established" ? "Clinical validation has not been established" : `Clinical validation status: ${modelStatus.clinical_validation_status}`}</li>
              <li>{modelStatus.human_review_required ? "Authorized human technical capture-quality review remains required; this is not clinical review" : "Human technical review requirement not indicated"}</li>
            </ul>
          </>
        ) : modelStatusUnavailable ? (
          <p>Model availability could not be verified. Do not treat this workflow as a disease classifier.</p>
        ) : (
          <p>Checking model availability… Until confirmed, no disease classification is offered.</p>
        )}
      </section>
      <div className="skin-intake-intro">
        <div className="eyebrow"><span className="eyebrow-dot" /> PRIVATE IMAGE INTAKE · RESEARCH PROTOTYPE</div>
        <h1>Share a skin image <em>with control.</em></h1>
        <p>Upload a clear image only if you choose to. MediPredict currently checks file safety and capture characteristics; it does not identify a skin condition, diagnose disease or recommend treatment.</p>
      </div>

      {result ? (
        <section className="skin-intake-result" aria-live="polite">
          <div className="skin-intake-result-mark" aria-hidden="true">✓</div>
          <div className="eyebrow">PRIVATE STORAGE CONFIRMED</div>
          <h2>Your image was securely received.</h2>
          <p>{result.message}</p>
          <dl className="skin-intake-result-meta">
            <div><dt>Submission reference</dt><dd>{result.prediction_id}</dd></div>
            <div><dt>Storage status</dt><dd>Stored privately</dd></div>
            <div><dt>Review status</dt><dd>Awaiting eligible human review</dd></div>
          </dl>
          {result.quality_warnings.length > 0 ? (
            <div className="skin-intake-warnings">
              <strong>Capture-quality suggestions</strong>
              <ul>{result.quality_warnings.map((warning) => <li key={warning}>{warning.replaceAll("_", " ")}</li>)}</ul>
              <small>These automated warnings are advisory only. They are not a clinical quality score or medical assessment.</small>
            </div>
          ) : (
            <p className="skin-intake-no-warnings">No basic capture-quality warnings were detected. This does not establish clinical suitability.</p>
          )}
          <div className="skin-intake-revoke">
            <div><strong>Change your mind about human review?</strong><small>You can revoke this separate consent. Existing minimal audit records are retained.</small></div>
            <button type="button" className="button button-secondary" disabled={revoking || Boolean(revocationMessage)} onClick={revokeReviewConsent}>
              {revoking ? "Revoking..." : revocationMessage ? "Review access revoked" : "Revoke review consent"}
            </button>
          </div>
          {revocationMessage && <p className="skin-intake-success" role="status">{revocationMessage}</p>}
          <button className="button button-primary" type="button" onClick={() => { setResult(null); setError(""); setRevocationMessage(""); }}>
            Upload another image <span aria-hidden="true">→</span>
          </button>
        </section>
      ) : (
        <form className="skin-intake-form" onSubmit={handleSubmit}>
          <section className="skin-intake-upload">
            <label htmlFor="skin-image-file">Choose a skin image</label>
            <p>Accepted formats: JPEG, PNG or WebP. Maximum file size: 8 MiB. Avoid including your face, identity documents or other identifying details.</p>
            <input id="skin-image-file" type="file" accept="image/jpeg,image/png,image/webp" onChange={handleFileChange} />
            {image && <div className="skin-intake-file-meta"><strong>{image.name}</strong><span>{(image.size / (1024 * 1024)).toFixed(2)} MiB</span></div>}
            {previewUrl && <div className="skin-intake-preview"><img src={previewUrl} alt="Preview of the selected skin image" /><small>Local preview only. The image is sent only after you submit the form.</small></div>}
          </section>

          <fieldset className="skin-intake-consents">
            <legend>Review each consent separately</legend>
            <p className="skin-intake-consent-intro">All three choices are required for this particular upload. You can choose not to upload.</p>
            <label className="skin-intake-consent-item">
              <input type="checkbox" checked={processingConsent} onChange={(event) => setProcessingConsent(event.target.checked)} />
              <span><strong>1. Image processing</strong><small>I agree that MediPredict may receive, validate, sanitize and privately store this image for the requested image workflow.</small></span>
            </label>
            <label className="skin-intake-consent-item">
              <input type="checkbox" checked={historyConsent} onChange={(event) => setHistoryConsent(event.target.checked)} />
              <span><strong>2. Image history and retention</strong><small>I agree that a private image-history record may be retained under the project&apos;s applicable retention policy. I understand that no default expiry is assumed by this prototype.</small></span>
            </label>
            <label className="skin-intake-consent-item">
              <input type="checkbox" checked={reviewConsent} onChange={(event) => setReviewConsent(event.target.checked)} />
              <span><strong>3. Human capture-quality review</strong><small>I agree that an explicitly assigned, authorized reviewer may view this image only to assess technical capture quality, such as framing, lighting and visibility. This is not clinical diagnosis.</small></span>
            </label>
          </fieldset>

          <div className="skin-intake-privacy-note">
            <strong>Privacy and safety</strong>
            <p>The image is stored in private object storage when configured. Reviewers receive image-specific access only after assignment. Do not upload an image if you are uncomfortable sharing it. For a changing, painful, bleeding or otherwise concerning skin problem, contact a qualified healthcare professional rather than waiting for this prototype.</p>
          </div>

          {error && <p className="skin-intake-error" role="alert">{error}</p>}
          <button className="button button-primary skin-intake-submit" type="submit" disabled={submitting || !image || !processingConsent || !historyConsent || !reviewConsent}>
            {submitting ? "Securely submitting..." : "Submit image with consent"} <span aria-hidden="true">→</span>
          </button>
          <p className="skin-intake-form-foot">Nothing is considered stored until the server confirms private storage. If storage is unavailable, the request fails closed.</p>
        </form>
      )}
      {error && result && <p className="skin-intake-error" role="alert">{error}</p>}
    </div>
  );
}
