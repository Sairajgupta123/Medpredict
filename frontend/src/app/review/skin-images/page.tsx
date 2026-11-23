import Link from "next/link";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import {
  API_BASE_URL,
  getSessionUser,
  SESSION_COOKIE,
} from "@/lib/auth-proxy";

type ReviewQueueItem = {
  prediction_id: string;
  review_status: "pending" | "assigned";
  quality_status: string;
  created_at: string;
  assigned_at: string | null;
  image_endpoint: string;
};

type EligibleReviewer = {
  id: string;
  email: string;
  display_name: string | null;
};

async function requireReviewerToken() {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) redirect("/login");
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) redirect("/login");
  const user = await response.json() as { role?: string };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");
  return { token, user };
}

async function assignImage(formData: FormData) {
  "use server";
  const { token, user } = await requireReviewerToken();
  if (user.role !== "admin") redirect("/review/skin-images?error=forbidden");
  const predictionId = String(formData.get("prediction_id") ?? "");
  const reviewerId = String(formData.get("reviewer_id") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!/^[0-9a-f-]{36}$/i.test(predictionId) || !/^[0-9a-f-]{36}$/i.test(reviewerId) || reason.length < 8 || reason.length > 1000) {
    redirect("/review/skin-images?error=invalid");
  }
  const scopeResponse = await fetch(`${API_BASE_URL}/admin/reviewer-scopes`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      reviewer_id: reviewerId,
      scope_type: "skin_image",
      scope_key: predictionId,
      reason: `Skin image assignment: ${reason}`.slice(0, 1000),
    }),
    cache: "no-store",
  });
  if (!scopeResponse.ok && scopeResponse.status !== 409) {
    redirect("/review/skin-images?error=scope");
  }
  const response = await fetch(`${API_BASE_URL}/skin-images/review/${encodeURIComponent(predictionId)}/assign`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ reviewer_id: reviewerId, reason }),
    cache: "no-store",
  });
  if (!response.ok) redirect(`/review/skin-images?error=${response.status === 409 ? "conflict" : "save"}`);
  revalidatePath("/review/skin-images");
  redirect("/review/skin-images?updated=assigned");
}

async function submitImageReview(formData: FormData) {
  "use server";
  const { token } = await requireReviewerToken();
  const predictionId = String(formData.get("prediction_id") ?? "");
  const outcome = String(formData.get("outcome") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!/^[0-9a-f-]{36}$/i.test(predictionId) || !["capture_adequate", "unable_to_assess"].includes(outcome) || reason.length < 8 || reason.length > 1000) {
    redirect("/review/skin-images?error=invalid");
  }
  const response = await fetch(`${API_BASE_URL}/skin-images/review/${encodeURIComponent(predictionId)}/decision`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ outcome, reason }),
    cache: "no-store",
  });
  if (!response.ok) redirect(`/review/skin-images?error=${response.status === 409 ? "conflict" : "save"}`);
  revalidatePath("/review/skin-images");
  redirect("/review/skin-images?updated=reviewed");
}

type PageProps = { searchParams: Promise<{ updated?: string; error?: string }> };

export default async function SkinImageReviewPage({ searchParams }: PageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const user = session.user as { role?: string; display_name?: string | null };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");
  const { token } = await requireReviewerToken();
  const params = await searchParams;

  let queue: ReviewQueueItem[] = [];
  let queueError: string | null = null;
  try {
    const response = await fetch(`${API_BASE_URL}/skin-images/review/queue`, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) queueError = "The skin-image review queue could not be loaded.";
    else queue = await response.json() as ReviewQueueItem[];
  } catch {
    queueError = "The MediPredict server is unavailable.";
  }

  let reviewers: EligibleReviewer[] = [];
  if (user.role === "admin") {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/reviewers`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
      });
      if (response.ok) reviewers = await response.json() as EligibleReviewer[];
    } catch {
      // The queue remains useful even if reviewer choices cannot be loaded.
    }
  }

  return (
    <main id="main-content" className="review-page">
      <section className="review-hero">
        <div className="container">
          <Link className="back-link" href="/review">← Back to review console</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> SKIN IMAGE REVIEW</div>
          <h1>Review image <em>capture quality.</em></h1>
          <p>Assigned reviewers can inspect retained images and record a technical capture-quality outcome. This workflow does not assess lesions or diagnose disease.</p>
          <div className="review-summary">
            <div><strong>{queue.length.toString().padStart(2, "0")}</strong><span>{user.role === "admin" ? "PENDING AND ASSIGNED" : "YOUR ASSIGNED ITEMS"}</span></div>
            <div><strong>{user.display_name || (user.role === "admin" ? "Administrator" : "Reviewer")}</strong><span>AUTHENTICATED ACCOUNT</span></div>
          </div>
        </div>
      </section>
      <section className="container review-content">
        {params.updated === "assigned" && <div className="review-alert review-alert-success" role="status">Image assignment saved.</div>}
        {params.updated === "reviewed" && <div className="review-alert review-alert-success" role="status">Technical image review saved.</div>}
        {params.error === "invalid" && <div className="review-alert" role="alert">Please check the selected reviewer, outcome and reason. The reason must contain 8–1,000 characters.</div>}
        {params.error === "forbidden" && <div className="review-alert" role="alert">Only administrators can assign images.</div>}
        {params.error === "conflict" && <div className="review-alert" role="alert">This image changed before your action. Refresh the queue and try again.</div>}
        {params.error === "save" && <div className="review-alert" role="alert">The action could not be saved. Please try again.</div>}
        {params.error === "scope" && <div className="review-alert" role="alert">The image-specific reviewer permission could not be granted. No assignment was made.</div>}
        {queueError && <div className="review-alert" role="alert">{queueError}</div>}
        <div className="review-section-heading">
          <div><span className="eyebrow">WORK QUEUE</span><h2>Skin-image submissions</h2></div>
          <span className="review-count">{queue.length} ITEMS</span>
        </div>
        {queue.length === 0 ? (
          <div className="review-empty"><h3>No images are waiting in this queue</h3><p>New images appear here after secure intake and consent checks. Administrators can assign pending items to verified reviewers.</p></div>
        ) : (
          <div className="review-list">
            {queue.map((item) => (
              <article className="review-card" key={item.prediction_id}>
                <div className="review-card-heading">
                  <div><span className="review-type">SKIN IMAGE</span><h3>Submission {item.prediction_id.slice(0, 8)}</h3><p className="review-key">Reference: {item.prediction_id}</p></div>
                  <span className={`review-status review-status-${item.review_status}`}>{item.review_status.replaceAll("_", " ")}</span>
                </div>
                <div className="review-item-meta">
                  <span>Capture check: {item.quality_status.replaceAll("_", " ")}</span>
                  <span>Received {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(item.created_at))}</span>
                </div>
                {item.review_status === "assigned" && (
                  <div className="skin-review-image-wrap">
                    <img
                      className="skin-review-image"
                      src={`/api/skin-images/review/${encodeURIComponent(item.prediction_id)}/image`}
                      alt="Privately served skin image for technical capture-quality review"
                    />
                    <p>Use this image only to assess capture quality, such as framing, lighting and visibility. Do not infer a diagnosis.</p>
                  </div>
                )}
                {user.role === "admin" && item.review_status === "pending" && (
                  <form action={assignImage} className="review-form">
                    <input type="hidden" name="prediction_id" value={item.prediction_id} />
                    <label>Assign to verified reviewer
                      <select name="reviewer_id" required defaultValue="">
                        <option value="" disabled>Select a reviewer</option>
                        {reviewers.map((reviewer) => <option key={reviewer.id} value={reviewer.id}>{reviewer.display_name || reviewer.email} — {reviewer.email}</option>)}
                      </select>
                    </label>
                    <label>Assignment reason
                      <textarea name="reason" minLength={8} maxLength={1000} rows={2} required placeholder="Explain why this submission is being assigned." />
                    </label>
                    <div className="review-form-footer"><small>Only active, verified reviewer accounts are assignable.</small><button className="button button-primary" type="submit" disabled={reviewers.length === 0}>Assign image →</button></div>
                  </form>
                )}
                {item.review_status === "assigned" && (
                  <form action={submitImageReview} className="review-form">
                    <input type="hidden" name="prediction_id" value={item.prediction_id} />
                    <label>Technical capture outcome
                      <select name="outcome" required defaultValue="">
                        <option value="" disabled>Select an outcome</option>
                        <option value="capture_adequate">Capture adequate for review</option>
                        <option value="unable_to_assess">Unable to assess capture</option>
                      </select>
                    </label>
                    <label>Review reason
                      <textarea name="reason" minLength={8} maxLength={1000} rows={3} required placeholder="Record only technical capture-quality observations." />
                    </label>
                    <div className="review-form-footer"><small>Do not enter diagnosis, suspected disease or treatment advice.</small><button className="button button-primary" type="submit">Save technical review →</button></div>
                  </form>
                )}
              </article>
            ))}
          </div>
        )}
        <div className="review-safety-note">
          <strong>Clinical safety boundary</strong>
          <p>Capture adequacy is not a clinical finding. This screen does not provide a diagnosis, risk score, disease classification or treatment recommendation. Reviewer access must be granted only after the organization verifies appropriate qualifications and scope.</p>
        </div>
      </section>
    </main>
  );
}
