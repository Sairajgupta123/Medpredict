import Link from "next/link";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import {
  API_BASE_URL,
  CatalogReviewQueueItem,
  getCatalogReviewHistory,
  getCatalogReviewQueue,
  getReviewerWorkload,
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
  const expectedStatus = String(formData.get("expected_status") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();

  if (
    !["disease", "symptom", "disease_symptom"].includes(targetType) ||
    !targetKey ||
    !allowedStatuses.has(status) ||
    !allowedStatuses.has(expectedStatus) ||
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
    body: JSON.stringify({ expected_status: expectedStatus, status, reason }),
    cache: "no-store",
  });

  if (response.status === 409) redirect("/review?error=conflict");
  if (!response.ok) redirect("/review?error=save");
  revalidatePath("/review");
  redirect("/review?updated=1");
}

type ReviewPageProps = {
  searchParams: Promise<{
    updated?: string;
    error?: string;
    q?: string;
    type?: string;
    status?: string;
    page?: string;
    history_q?: string;
    history_type?: string;
    history_from?: string;
    history_to?: string;
  }>;
};

export default async function ReviewPage({ searchParams }: ReviewPageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");

  const user = session.user as { role?: string; display_name?: string | null };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");

  const params = await searchParams;
  const query = (params.q ?? "").trim().slice(0, 120);
  const selectedType = ["disease", "symptom", "disease_symptom"].includes(params.type ?? "")
    ? params.type
    : "all";
  const selectedStatus = ["draft", "in_review"].includes(params.status ?? "")
    ? params.status
    : "all";
  const parsedPage = Number.parseInt(params.page ?? "1", 10);
  const pageNumber = Number.isSafeInteger(parsedPage) && parsedPage > 0
    ? Math.min(parsedPage, 500)
    : 1;
  const pageSize = 20;
  const historyQuery = (params.history_q ?? "").trim().slice(0, 120);
  const historyType = ["disease", "symptom", "disease_symptom"].includes(params.history_type ?? "")
    ? params.history_type
    : "all";
  const historyFrom = /^\d{4}-\d{2}-\d{2}$/.test(params.history_from ?? "")
    ? params.history_from ?? ""
    : "";
  const historyTo = /^\d{4}-\d{2}-\d{2}$/.test(params.history_to ?? "")
    ? params.history_to ?? ""
    : "";

  const [
    { items: queueWindow, error },
    { items: history, error: historyError },
    { data: workload, error: workloadError },
  ] = await Promise.all([
    getCatalogReviewQueue({
      q: query,
      target_type: selectedType,
      status: selectedStatus,
      offset: (pageNumber - 1) * pageSize,
      limit: pageSize,
    }),
    getCatalogReviewHistory({
      q: historyQuery,
      target_type: historyType,
      date_from: historyFrom,
      date_to: historyTo,
    }),
    getReviewerWorkload(),
  ]);

  const queueHasMore = queueWindow.length > pageSize;
  const items = queueWindow.slice(0, pageSize);
  const queuePageParams = new URLSearchParams({
    page: String(pageNumber),
    q: query,
    type: selectedType ?? "all",
    status: selectedStatus ?? "all",
    history_q: historyQuery,
    history_type: historyType ?? "all",
    history_from: historyFrom,
    history_to: historyTo,
  });

  return (
    <main id="main-content" className="review-page">
      <section className="review-hero">
        <div className="container">
          <Link className="back-link" href="/dashboard">← Back to workspace</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> CATALOG GOVERNANCE</div>
          <h1>Review with <em>care and evidence.</em></h1>
          <p>Review pending catalog entries against approved, reliable sources. Every decision requires a reason and is recorded in the audit history.</p>
          <Link className="review-page-link" href="/review/skin-images">Open skin-image capture review →</Link>
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
        {params.error === "conflict" && <div className="review-alert" role="alert">This entry was changed by another reviewer after you opened it. The queue has been refreshed; please review the latest status before deciding.</div>}
        {error && <div className="review-alert" role="alert">{error}</div>}

        <section className="review-workload" aria-labelledby="review-workload-title">
          <div className="review-section-heading">
            <div>
              <span className="eyebrow">ASSIGNED RESPONSIBILITIES</span>
              <h2 id="review-workload-title">Your review workload</h2>
            </div>
            <span className="review-count">LIVE SUMMARY</span>
          </div>
          {workloadError ? (
            <div className="review-alert" role="alert">{workloadError}</div>
          ) : workload ? (
            <>
              <div className="review-assignment-panel">
                <div className="review-assignment-heading">
                  <strong>Active assignments</strong>
                  <span>{workload.is_unrestricted ? "Administrator access" : `${workload.assignments.length} assigned scope${workload.assignments.length === 1 ? "" : "s"}`}</span>
                </div>
                {workload.is_unrestricted ? (
                  <p className="review-assignment-empty">Administrators have unrestricted catalog review access.</p>
                ) : workload.assignments.length === 0 ? (
                  <p className="review-assignment-empty">No active review scopes are assigned to your account. Contact an administrator if you need a responsibility assigned.</p>
                ) : (
                  <ul className="review-assignment-list">
                    {workload.assignments.map((assignment) => (
                      <li key={`${assignment.scope_type}:${assignment.scope_key ?? "all"}`}>
                        <span className="review-assignment-type">{assignment.scope_type.replaceAll("_", " ")}</span>
                        <strong>{assignment.scope_key ?? `All ${assignment.scope_type === "disease_symptom" ? "disease–symptom relationships" : `${assignment.scope_type}s`}`}</strong>
                        <small>Assigned {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(assignment.granted_at))}</small>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="review-workload-grid">
                <article className="review-workload-card review-workload-primary">
                  <span>Pending items</span>
                  <strong>{workload.pending_total}</strong>
                  <small>Across your active assignments</small>
                </article>
                <article className="review-workload-card">
                  <span>Diseases</span>
                  <strong>{workload.pending_by_type.disease}</strong>
                  <small>Pending disease reviews</small>
                </article>
                <article className="review-workload-card">
                  <span>Symptoms</span>
                  <strong>{workload.pending_by_type.symptom}</strong>
                  <small>Pending symptom reviews</small>
                </article>
                <article className="review-workload-card">
                  <span>Relationships</span>
                  <strong>{workload.pending_by_type.disease_symptom}</strong>
                  <small>Pending disease–symptom links</small>
                </article>
              </div>
              <div className="review-activity-strip">
                <div><strong>{workload.activity.total_decisions}</strong><span>Total decisions recorded</span></div>
                <div><strong>{workload.activity.approved_decisions}</strong><span>Approvals recorded</span></div>
                <div><strong>{workload.activity.retired_decisions}</strong><span>Retirements recorded</span></div>
                <div><strong>{workload.activity.decisions_last_7_days}</strong><span>Decisions in last 7 days</span></div>
              </div>
              <p className="review-workload-note">Workload counts include only items in your active review scope. Activity figures reflect decisions recorded under your account.</p>
            </>
          ) : null}
        </section>

        <div className="review-section-heading">
          <div><span className="eyebrow">PENDING DECISIONS</span><h2 id="queue-title">Catalog review queue</h2></div>
          <span className="review-count">PAGE {pageNumber} · {items.length} ITEMS</span>
        </div>

        <form method="get" className="review-filters" role="search" aria-label="Filter catalog review queue">
          <input type="hidden" name="page" value="1" />
          <input type="hidden" name="history_q" value={historyQuery} />
          <input type="hidden" name="history_type" value={historyType} />
          <input type="hidden" name="history_from" value={historyFrom} />
          <input type="hidden" name="history_to" value={historyTo} />
          <label>
            Search entries
            <input type="search" name="q" defaultValue={query} maxLength={120} placeholder="Search name, code or description" />
          </label>
          <label>
            Entry type
            <select name="type" defaultValue={selectedType}>
              <option value="all">All types</option>
              <option value="disease">Diseases</option>
              <option value="symptom">Symptoms</option>
              <option value="disease_symptom">Disease–symptom links</option>
            </select>
          </label>
          <label>
            Review status
            <select name="status" defaultValue={selectedStatus}>
              <option value="all">All pending statuses</option>
              <option value="draft">Draft</option>
              <option value="in_review">In review</option>
            </select>
          </label>
          <div className="review-filter-actions">
            <button className="button button-primary" type="submit">Apply filters</button>
            <Link href="/review" className="review-clear-filters">Clear</Link>
          </div>
        </form>

        {items.length === 0 && !error ? (
          <div className="review-empty">
            <span aria-hidden="true">✓</span>
            <h3>{pageNumber > 1 ? "No entries on this page" : "No matching entries"}</h3>
            <p>{pageNumber > 1
              ? "There are no more matching entries on this page. Go back to the previous page."
              : "There are no entries matching your current search and filters."}</p>
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
                <div className="review-item-meta">
                  <span>Catalog entry</span>
                  {item.created_at && <span>Added {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(item.created_at))}</span>}
                  <Link
                    className="review-page-link"
                    href={`/review/entry?type=${encodeURIComponent(item.target_type)}&key=${encodeURIComponent(item.target_key)}`}
                  >Inspect entry and context →</Link>
                </div>
                <form action={submitReview} className="review-form">
                  <input type="hidden" name="target_type" value={item.target_type} />
                  <input type="hidden" name="target_key" value={item.target_key} />
                  <input type="hidden" name="expected_status" value={item.status} />
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
        <nav className="review-pagination" aria-label="Review queue pages">
          {pageNumber > 1 ? (
            <Link
              className="review-page-link"
              href={`/review?${new URLSearchParams({ ...Object.fromEntries(queuePageParams), page: String(pageNumber - 1) }).toString()}#queue-title`}
              rel="prev"
            >← Previous page</Link>
          ) : <span className="review-page-disabled">← Previous page</span>}
          <span className="review-page-indicator">Page {pageNumber}</span>
          {queueHasMore ? (
            <Link
              className="review-page-link"
              href={`/review?${new URLSearchParams({ ...Object.fromEntries(queuePageParams), page: String(pageNumber + 1) }).toString()}#queue-title`}
              rel="next"
            >Next page →</Link>
          ) : <span className="review-page-disabled">Next page →</span>}
        </nav>

        <section className="review-history-section" aria-labelledby="review-history-title">
          <div className="review-section-heading">
            <div>
              <span className="eyebrow">TRACEABILITY</span>
              <h2 id="review-history-title">Review decision history</h2>
            </div>
            <span className="review-count">{history.length} MATCHING DECISIONS</span>
          </div>
          <form method="get" className="review-history-filters" role="search" aria-label="Filter review decision history">
            <input type="hidden" name="q" value={query} />
            <input type="hidden" name="type" value={selectedType} />
            <input type="hidden" name="status" value={selectedStatus} />
            <input type="hidden" name="page" value="1" />
            <label>
              Search code or reason
              <input type="search" name="history_q" maxLength={120} defaultValue={historyQuery} placeholder="Search reviewed code or decision reason" />
            </label>
            <label>
              Category
              <select name="history_type" defaultValue={historyType}>
                <option value="all">All categories</option>
                <option value="disease">Diseases</option>
                <option value="symptom">Symptoms</option>
                <option value="disease_symptom">Disease–symptom links</option>
              </select>
            </label>
            <label>
              From date
              <input type="date" name="history_from" defaultValue={historyFrom} />
            </label>
            <label>
              To date
              <input type="date" name="history_to" defaultValue={historyTo} />
            </label>
            <div className="review-filter-actions">
              <button className="button button-primary" type="submit">Filter history</button>
              <Link href="/review#review-history-title" className="review-clear-filters">Clear</Link>
            </div>
          </form>
          {historyError ? (
            <div className="review-alert" role="alert">{historyError}</div>
          ) : history.length === 0 ? (
            <div className="review-history-empty">No decisions match these filters. Try a wider date range or a different search.</div>
          ) : (
            <div className="review-history-list">
              {history.map((event) => (
                <article className="review-history-card" key={event.id}>
                  <div className="review-history-topline">
                    <span className="review-type">{event.target_type.replaceAll("_", " ")}</span>
                    <time dateTime={event.created_at}>
                      {new Intl.DateTimeFormat("en-IN", {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }).format(new Date(event.created_at))}
                    </time>
                  </div>
                  <div className="review-history-change">
                    <strong>{event.target_key}</strong>
                    <span>{event.previous_status.replaceAll("_", " ")} <span aria-hidden="true">→</span> {event.new_status.replaceAll("_", " ")}</span>
                  </div>
                  <p>{event.reason}</p>
                  <div className="review-history-footer">
                    <small>Reviewer ID: {event.reviewer_id}</small>
                    <Link href={`/review/history/${event.id}`}>Open catalog entry <span aria-hidden="true">→</span></Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <div className="review-safety-note">
          <strong>Review boundary</strong>
          <p>Approval is a content-governance decision, not proof of clinical validity. Only review material within your verified qualifications and assigned scope. The reviewer queue does not provide diagnosis or treatment recommendations.</p>
        </div>
      </section>
    </main>
  );
}
