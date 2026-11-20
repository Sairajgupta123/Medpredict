import Link from "next/link";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import {
  API_BASE_URL,
  CatalogReviewQueueItem,
  getCatalogReviewQueue,
  getSessionUser,
  SESSION_COOKIE,
} from "@/lib/auth-proxy";

const allowedStatuses = new Set(["draft", "in_review", "approved", "retired"]);

async function submitReview(formData: FormData) {
  "use server";

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) redirect("/login");

  const sessionResponse = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    cache: "no-store",
  });
  if (!sessionResponse.ok) redirect("/login");
  const user = await sessionResponse.json() as { role?: string };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");

  const targetType = String(formData.get("target_type") ?? "");
  const targetKey = String(formData.get("target_key") ?? "");
  const status = String(formData.get("status") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();

  if (
    !["disease", "symptom", "disease_symptom"].includes(targetType) ||
    !targetKey ||
    !allowedStatuses.has(status) ||
    reason.length < 8 ||
    reason.length > 1000
  ) {
    redirect("/review?error=invalid");
  }

  let endpoint: string;
  if (targetType === "disease") {
    endpoint = `/catalog/review/diseases/${encodeURIComponent(targetKey)}`;
  } else if (targetType === "symptom") {
    endpoint = `/catalog/review/symptoms/${encodeURIComponent(targetKey)}`;
  } else {
    const [diseaseCode, symptomCode, ...rest] = targetKey.split(":");
    if (!diseaseCode || !symptomCode || rest.length) redirect("/review?error=invalid");
    endpoint = `/catalog/review/diseases/${encodeURIComponent(diseaseCode)}/symptoms/${encodeURIComponent(symptomCode)}`;
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ status, reason }),
    cache: "no-store",
  });

  if (!response.ok) redirect("/review?error=save");
  revalidatePath("/review");
  redirect("/review?updated=1");
}

type ReviewPageProps = {
  searchParams: Promise<{ updated?: string; error?: string }>;
};

export default async function ReviewPage({ searchParams }: ReviewPageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");

  const user = session.user as { role?: string; display_name?: string | null };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");

  const [{ items, error }, params] = await Promise.all([
    getCatalogReviewQueue(),
    searchParams,
  ]);

  return (
    <main id="main-content" className="review-page">
      <section className="review-hero">
        <div className="container">
          <Link className="back-link" href="/dashboard">← Back to workspace</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> CATALOG GOVERNANCE</div>
          <h1>Review with <em>care and evidence.</em></h1>
          <p>Review pending catalog entries against approved, reliable sources. Every decision requires a reason and is recorded in the audit history.</p>
          <div className="review-summary">
            <div><strong>{items.length.toString().padStart(2, "0")}</strong><span>ITEMS IN THIS QUEUE</span></div>
            <div><strong>{user.display_name || "Reviewer"}</strong><span>AUTHENTICATED REVIEWER</span></div>
          </div>
        </div>
      </section>

      <section className="container review-content">
        {params.updated === "1" && <div className="review-alert review-alert-success" role="status">Your review decision has been saved.</div>}
        {params.error === "invalid" && <div className="review-alert" role="alert">Please check the item, status and reason. Reasons must contain at least 8 characters.</div>}
        {params.error === "save" && <div className="review-alert" role="alert">The review decision could not be saved. Please refresh and try again.</div>}
        {error && <div className="review-alert" role="alert">{error}</div>}

        <div className="review-section-heading">
          <div><span className="eyebrow">PENDING DECISIONS</span><h2>Catalog review queue</h2></div>
          <span className="review-count">{items.length} {items.length === 1 ? "ITEM" : "ITEMS"}</span>
        </div>

        {items.length === 0 && !error ? (
          <div className="review-empty">
            <span aria-hidden="true">✓</span>
            <h3>No pending entries</h3>
            <p>There are no draft or in-review catalog entries in your current queue.</p>
          </div>
        ) : (
          <div className="review-list">
            {items.map((item: CatalogReviewQueueItem) => (
              <article className="review-card" key={`${item.target_type}:${item.target_key}`}>
                <div className="review-card-heading">
                  <div>
                    <span className="review-type">{item.target_type.replaceAll("_", " ")}</span>
                    <h3>{item.name}</h3>
                    <p className="review-key">{item.target_key}</p>
                  </div>
                  <span className={`review-status review-status-${item.status}`}>{item.status.replaceAll("_", " ")}</span>
                </div>
                {item.description && <p className="review-description">{item.description}</p>}
                <form action={submitReview} className="review-form">
                  <input type="hidden" name="target_type" value={item.target_type} />
                  <input type="hidden" name="target_key" value={item.target_key} />
                  <label>
                    Decision
                    <select name="status" defaultValue="in_review" required>
                      <option value="in_review">Keep in review</option>
                      <option value="approved">Approve</option>
                      <option value="retired">Retire</option>
                      <option value="draft">Return to draft</option>
                    </select>
                  </label>
                  <label>
                    Review reason
                    <textarea name="reason" minLength={8} maxLength={1000} rows={3} required placeholder="Record the evidence checked and why this decision is appropriate." />
                  </label>
                  <div className="review-form-footer">
                    <small>8–1,000 characters. This reason becomes part of the audit record.</small>
                    <button className="button button-primary" type="submit">Save decision <span aria-hidden="true">→</span></button>
                  </div>
                </form>
              </article>
            ))}
          </div>
        )}

        <div className="review-safety-note">
          <strong>Review boundary</strong>
          <p>Approval is a content-governance decision, not proof of clinical validity. Only review material within your verified qualifications and assigned scope. The reviewer queue does not provide diagnosis or treatment recommendations.</p>
        </div>
      </section>
    </main>
  );
}
