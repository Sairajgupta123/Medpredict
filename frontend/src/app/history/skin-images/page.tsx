import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { API_BASE_URL, getSessionToken, getSessionUser } from "@/lib/auth-proxy";

export const metadata: Metadata = { title: "Your skin image history" };

type HistoryItem = {
  id: string;
  modality: string;
  status: string;
  model_version: string | null;
  disclaimer_version: string | null;
  created_at: string;
  completed_at: string | null;
};

type HistoryPage = {
  items: HistoryItem[];
  total: number;
  limit: number;
  offset: number;
};

type OwnerReviewStatus = {
  prediction_id: string;
  status: string;
  status_label: string;
  status_detail: string;
  next_step: string;
  status_at: string | null;
  clinical_interpretation_performed: false;
  disease_prediction_performed: false;
};

async function deleteSkinImageHistory(formData: FormData) {
  "use server";
  const predictionId = String(formData.get("prediction_id") ?? "");
  const confirmation = String(formData.get("confirmation") ?? "");
  if (!/^[0-9a-f-]{36}$/i.test(predictionId) || confirmation !== "DELETE") redirect("/history/skin-images?error=delete-confirmation");
  const token = await getSessionToken();
  if (!token) redirect("/login");
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/predictions/history/${encodeURIComponent(predictionId)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
  } catch {
    redirect("/history/skin-images?error=delete-unavailable");
  }
  if (response.status === 204) {
    revalidatePath("/history/skin-images");
    redirect(`/history/skin-images?deleted=${encodeURIComponent(predictionId)}&receipt=${encodeURIComponent(new Date().toISOString())}`);
  }
  if (response.status === 404) redirect("/history/skin-images?error=delete-not-found");
  if (response.status === 503) redirect("/history/skin-images?error=delete-pending");
  if (response.status === 409) redirect("/history/skin-images?error=delete-blocked");
  redirect("/history/skin-images?error=delete-failed");
}

async function revokeReviewConsent(formData: FormData) {
  "use server";
  const predictionId = String(formData.get("prediction_id") ?? "");
  if (!/^[0-9a-f-]{36}$/i.test(predictionId)) redirect("/history/skin-images?error=invalid");
  const token = await getSessionToken();
  if (!token) redirect("/login");

  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/skin-images/${encodeURIComponent(predictionId)}/revoke-review-consent`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(8_000),
      },
    );
  } catch {
    redirect("/history/skin-images?error=unavailable");
  }

  if (response.status === 409) redirect("/history/skin-images?error=already-revoked");
  if (!response.ok) redirect("/history/skin-images?error=save");

  let result: unknown;
  try {
    result = await response.json();
  } catch {
    redirect("/history/skin-images?error=save");
  }
  if (
    !result
    || typeof result !== "object"
    || !("prediction_id" in result)
    || result.prediction_id !== predictionId
    || !("consent_status" in result)
    || result.consent_status !== "revoked"
    || !("reviewer_access_revoked" in result)
    || result.reviewer_access_revoked !== true
  ) {
    redirect("/history/skin-images?error=save");
  }

  revalidatePath("/history/skin-images");
  redirect("/history/skin-images?updated=revoked");
}

type PageProps = { searchParams: Promise<{ updated?: string; deleted?: string; receipt?: string; error?: string; offset?: string }> };

export default async function SkinImageHistoryPage({ searchParams }: PageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const token = await getSessionToken();
  const params = await searchParams;
  const pageSize = 100;
  const requestedOffset = Number(params.offset ?? "0");
  const offset = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0;

  let historyTotal = 0;
  let items: HistoryItem[] = [];
  const reviewStatuses: Record<string, OwnerReviewStatus> = {};
  let loadError = "";
  if (token) {
    try {
      const response = await fetch(`${API_BASE_URL}/predictions/history?limit=${pageSize}&offset=${offset}`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
      if (response.ok) {
        const payload: unknown = await response.json();
        const validHistoryPage = (value: unknown): value is HistoryPage => {
          if (!value || typeof value !== "object" || Array.isArray(value)) return false;
          const candidate = value as Record<string, unknown>;
          if (!Array.isArray(candidate.items)
            || !Number.isSafeInteger(candidate.total)
            || (candidate.total as number) < 0
            || candidate.limit !== pageSize
            || candidate.offset !== offset
            || candidate.items.length > pageSize) return false;
          const ids = new Set<string>();
          return candidate.items.every((entry) => {
            if (!entry || typeof entry !== "object" || Array.isArray(entry)) return false;
            const item = entry as Record<string, unknown>;
            if (typeof item.id !== "string" || !/^[0-9a-f-]{36}$/i.test(item.id) || ids.has(item.id)) return false;
            if (typeof item.modality !== "string" || !["text", "skin_image", "combined"].includes(item.modality)) return false;
            if (typeof item.status !== "string" || item.status.length > 80) return false;
            if (!(item.model_version === null || typeof item.model_version === "string")) return false;
            if (!(item.disclaimer_version === null || typeof item.disclaimer_version === "string")) return false;
            if (typeof item.created_at !== "string" || !Number.isFinite(Date.parse(item.created_at))) return false;
            if (!(item.completed_at === null || (typeof item.completed_at === "string" && Number.isFinite(Date.parse(item.completed_at))))) return false;
            ids.add(item.id);
            return true;
          });
        };
        if (validHistoryPage(payload)) {
          historyTotal = payload.total;
          if (historyTotal > 0 && offset >= historyTotal) {
            redirect(`/history/skin-images?offset=${Math.floor((historyTotal - 1) / pageSize) * pageSize}`);
          }
          items = payload.items.filter((item) => item.modality === "skin_image" || item.modality === "combined");
          // Keep per-image status lookups bounded so a full history page does
          // not open 100 simultaneous backend requests.
          let nextStatusIndex = 0;
          const statusWorker = async () => {
            while (nextStatusIndex < items.length) {
              const item = items[nextStatusIndex++];
              try {
                const statusResponse = await fetch(
                  `${API_BASE_URL}/skin-images/${encodeURIComponent(item.id)}/review-status`,
                  {
                    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
                    cache: "no-store",
                    signal: AbortSignal.timeout(5000),
                  },
                );
                if (statusResponse.ok) {
                  const rawStatusPayload: unknown = await statusResponse.json();
                  const isRecord = (value: unknown): value is Record<string, unknown> =>
                    Boolean(value) && typeof value === "object" && !Array.isArray(value);
                  const statusPayload = isRecord(rawStatusPayload) ? rawStatusPayload : null;
                  const allowedStatuses = new Set([
                    "review_access_withdrawn",
                    "submission_unavailable",
                    "awaiting_review",
                    "assigned",
                    "reviewed",
                    "unable_to_assess",
                  ]);
                  const validStatusAt = statusPayload?.status_at === null
                    || (typeof statusPayload?.status_at === "string"
                      && Number.isFinite(Date.parse(statusPayload.status_at)));
                  if (statusPayload
                    && statusPayload.prediction_id === item.id
                    && typeof statusPayload.status === "string"
                    && allowedStatuses.has(statusPayload.status)
                    && typeof statusPayload.status_label === "string"
                    && statusPayload.status_label.trim().length > 0
                    && statusPayload.status_label.length <= 120
                    && typeof statusPayload.status_detail === "string"
                    && statusPayload.status_detail.trim().length > 0
                    && statusPayload.status_detail.length <= 500
                    && typeof statusPayload.next_step === "string"
                    && statusPayload.next_step.trim().length > 0
                    && statusPayload.next_step.length <= 500
                    && validStatusAt
                    && statusPayload.clinical_interpretation_performed === false
                    && statusPayload.disease_prediction_performed === false) {
                    reviewStatuses[item.id] = statusPayload as unknown as OwnerReviewStatus;
                  }
                }
              } catch {
                // Keep the history record visible if the separate status request fails.
              }
            }
          };
          const workerCount = Math.min(8, items.length);
          await Promise.all(Array.from({ length: workerCount }, () => statusWorker()));
        } else loadError = "The history service returned an unexpected response.";
      } else loadError = "Your image history could not be loaded.";
    } catch {
      loadError = "The MediPredict server is unavailable.";
    }
  } else {
    loadError = "Your session has expired. Please sign in again.";
  }

  return (
    <main id="main-content" className="review-page skin-history-page">
      <section className="review-hero">
        <div className="container">
          <Link className="back-link" href="/dashboard">← Back to workspace</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> PRIVATE IMAGE HISTORY</div>
          <h1>Your submissions, <em>your control.</em></h1>
          <p>Only metadata for your own image submissions is listed here. Image bytes, storage keys and reviewer notes are not exposed in this history view.</p>
          <div className="review-summary">
            <div><strong>{items.length.toString().padStart(2, "0")}</strong><span>IMAGE SUBMISSIONS ON THIS PAGE</span></div>
            <div><strong>Owner only</strong><span>AUTHENTICATED ACCOUNT</span></div>
          </div>
        </div>
      </section>
      <section className="container review-content">
        {params.updated === "revoked" && <div className="review-alert review-alert-success" role="status">Human-review consent was revoked. Reviewer access for that image has been disabled.</div>}
        {params.deleted && /^[0-9a-f-]{36}$/i.test(params.deleted) && <div className="review-alert review-alert-success" role="status"><strong>Deletion confirmed.</strong> Private image deletion and history-record removal were confirmed for reference {params.deleted.slice(0, 8)}.{params.receipt && !Number.isNaN(Date.parse(params.receipt)) ? ` Receipt time: ${new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(params.receipt))}.` : ""} The minimal independent review audit trail may remain.</div>}
        {params.error === "invalid" && <div className="review-alert" role="alert">The selected image reference is invalid.</div>}
        {params.error === "already-revoked" && <div className="review-alert" role="status">No active human-review consent was found for that image.</div>}
        {params.error === "unavailable" && <div className="review-alert" role="alert">The consent service is unavailable. Revocation was not confirmed.</div>}
        {params.error === "save" && <div className="review-alert" role="alert">The consent change could not be confirmed.</div>}
        {params.error === "delete-confirmation" && <div className="review-alert" role="alert">Deletion was not submitted. Type DELETE exactly to confirm permanent removal.</div>}
        {params.error === "delete-unavailable" && <div className="review-alert" role="alert">The deletion service is unavailable. No deletion was confirmed; retry later.</div>}
        {params.error === "delete-pending" && <div className="review-alert" role="alert">Private image deletion is pending. Your history record has been retained so cleanup can be retried. Do not assume the image has been deleted.</div>}
        {params.error === "delete-blocked" && <div className="review-alert" role="alert">The image storage state could not be safely verified. The record was retained for manual reconciliation.</div>}
        {params.error === "delete-not-found" && <div className="review-alert" role="status">This history item was not found in your account.</div>}
        {params.error === "delete-failed" && <div className="review-alert" role="alert">Deletion could not be confirmed. The item may still be retained; contact support or retry.</div>}
        {loadError && <div className="review-alert" role="alert">{loadError}</div>}
        <div className="review-section-heading">
          <div><span className="eyebrow">YOUR RECORDS</span><h2>Skin image submissions</h2></div>
          <Link className="review-page-link" href="/skin-image">Upload another image →</Link>
        </div>
        {!loadError && items.length === 0 ? (
          <div className="review-empty"><h3>{historyTotal > 0 ? "No skin-image submissions on this page" : "No skin-image submissions yet"}</h3><p>{historyTotal > 0 ? "This page contains other history types. Use the history navigation below to check older or newer records." : "When you submit an image with all required consents, its private history metadata will appear here."}</p>{historyTotal === 0 && <Link className="button button-primary" href="/skin-image">Start a private upload →</Link>}</div>
        ) : (
          <div className="review-list">
            {items.map((item) => (
              <article className="review-card skin-history-card" key={item.id}>
                <div className="review-card-heading">
                  <div><span className="review-type">PRIVATE SKIN IMAGE</span><h3>Submission {item.id.slice(0, 8)}</h3><p className="review-key">Reference: {item.id}</p></div>
                  <span className="review-status review-status-assigned">{reviewStatuses[item.id]?.status_label ?? "Review status unavailable"}</span>
                </div>
                {reviewStatuses[item.id] && (
                  <div className="skin-owner-review-guidance" aria-label="Technical review information">
                    <div><strong>What this means</strong><p>{reviewStatuses[item.id].status_detail}</p></div>
                    <div><strong>Next step</strong><p>{reviewStatuses[item.id].next_step}</p></div>
                  </div>
                )}
                <div className="review-item-meta">
                  <span>Submitted {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.created_at))}</span>
                  <span>Image contents are not included in this list</span>
                  {reviewStatuses[item.id]?.status_at && <span>Status updated {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(reviewStatuses[item.id].status_at as string))}</span>}
                </div>
                <form action={deleteSkinImageHistory} className="skin-history-action skin-history-delete-action">
                  <input type="hidden" name="prediction_id" value={item.id} />
                  <div>
                    <strong>Delete image and history permanently</strong>
                    <small>This removes the private image object first, then removes this history record and linked consent data. Independent technical-review audit events may remain without the image or patient record.</small>
                    <label className="skin-delete-confirm-label" htmlFor={`delete-confirm-${item.id}`}>Type DELETE to confirm</label>
                    <input id={`delete-confirm-${item.id}`} name="confirmation" type="text" required pattern="DELETE" autoComplete="off" spellCheck={false} />
                    <small>This action cannot be undone. If private storage is unavailable, deletion will not be reported as complete.</small>
                  </div>
                  <button className="button button-danger" type="submit">Permanently delete</button>
                </form>
                <form action={revokeReviewConsent} className="skin-history-action">
                  <input type="hidden" name="prediction_id" value={item.id} />
                  <div><strong>Human-review permission</strong><small>Revoke the separate consent and disable assigned reviewer access for this image.</small></div>
                  <button className="button button-secondary" type="submit">Revoke review consent</button>
                </form>
              </article>
            ))}
          </div>
        )}
        {!loadError && historyTotal > pageSize && (
          <nav className="review-pagination" aria-label="History pagination">
            {offset > 0 && <Link className="button button-secondary" href={`/history/skin-images?offset=${Math.max(0, offset - pageSize)}`}>← Newer records</Link>}
            <span>Showing history records {offset + 1}–{Math.min(offset + pageSize, historyTotal)} of {historyTotal}. Other record types may also appear in these pages.</span>
            {offset + pageSize < historyTotal && <Link className="button button-secondary" href={`/history/skin-images?offset=${offset + pageSize}`}>Older records →</Link>}
          </nav>
        )}
        <div className="review-safety-note">
          <strong>Technical review only</strong>
          <p>The status describes image handling and capture-quality review only. It is not a diagnosis, disease-risk estimate, or medical interpretation.</p>
          <strong>Separate controls</strong>
          <p>Revoking human-review consent does not delete your image-history record. Permanent deletion is a separate action: the private image object is removed first, then the history record and linked consent data. Independent technical-review audit events may remain.</p>
        </div>
      </section>
    </main>
  );
}
