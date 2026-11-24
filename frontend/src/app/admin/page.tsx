import Link from "next/link";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import {
  API_BASE_URL,
  getGovernanceOverview,
  getReviewerScopeGovernance,
  getSessionUser,
  SESSION_COOKIE,
} from "@/lib/auth-proxy";

const reviewStatuses = ["draft", "in_review", "approved", "retired"] as const;

function total(values: Record<string, number>) {
  return Object.values(values).reduce((sum, value) => sum + value, 0);
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

async function requireAdminToken() {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) redirect("/login");
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) redirect("/login");
  const user = await response.json() as { role?: string };
  if (user.role !== "admin") redirect("/dashboard");
  return token;
}

async function grantReviewerScope(formData: FormData) {
  "use server";
  const token = await requireAdminToken();
  const reviewerId = String(formData.get("reviewer_id") ?? "");
  const scopeType = String(formData.get("scope_type") ?? "");
  const scopeKey = String(formData.get("scope_key") ?? "").trim();
  const reason = String(formData.get("reason") ?? "").trim();
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(reviewerId) ||
    !["disease", "symptom", "disease_symptom"].includes(scopeType) ||
    scopeKey.length > 200 ||
    reason.length < 8 ||
    reason.length > 1000
  ) redirect("/admin?scope_error=invalid");

  const response = await fetch(`${API_BASE_URL}/admin/reviewer-scopes`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      reviewer_id: reviewerId,
      scope_type: scopeType,
      scope_key: scopeKey || null,
      reason,
    }),
    cache: "no-store",
  });
  if (response.status === 409) redirect("/admin?scope_error=duplicate");
  if (!response.ok) redirect("/admin?scope_error=grant");
  revalidatePath("/admin");
  redirect("/admin?scope_updated=granted");
}

async function createMedicalReference(formData: FormData) {
  "use server";
  const token = await requireAdminToken();
  const title = String(formData.get("title") ?? "").trim();
  const publisher = String(formData.get("publisher") ?? "").trim();
  const url = String(formData.get("url") ?? "").trim();
  const evidenceType = String(formData.get("evidence_type") ?? "").trim();
  const version = String(formData.get("version") ?? "1").trim();
  const publishedOn = String(formData.get("published_on") ?? "").trim();
  const accessedOn = String(formData.get("accessed_on") ?? "").trim();
  const nextReviewDue = String(formData.get("next_review_due") ?? "").trim();
  const licenseName = String(formData.get("license_name") ?? "").trim();
  const contentHash = String(formData.get("content_sha256") ?? "").trim();
  const reason = String(formData.get("reason") ?? "").trim();
  if (
    title.length < 3 || title.length > 300 ||
    publisher.length < 2 || publisher.length > 200 ||
    !url || url.length > 1000 ||
    evidenceType.length < 2 || evidenceType.length > 80 ||
    version.length < 1 || version.length > 80 ||
    licenseName.length > 200 ||
    reason.length < 8 || reason.length > 1000
  ) {
    redirect("/admin?reference_error=invalid");
  }
  try {
    const parsedUrl = new URL(url);
    if (parsedUrl.protocol !== "https:" && parsedUrl.protocol !== "http:") {
      redirect("/admin?reference_error=invalid");
    }
  } catch {
    redirect("/admin?reference_error=invalid");
  }
  if (contentHash && !/^[a-fA-F0-9]{64}$/.test(contentHash)) {
    redirect("/admin?reference_error=invalid");
  }
  const response = await fetch(`${API_BASE_URL}/admin/medical-references`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      title, publisher, url, evidence_type: evidenceType, version,
      published_on: publishedOn || null,
      accessed_on: accessedOn || new Date().toISOString().slice(0, 10),
      next_review_due: nextReviewDue || null,
      license_name: licenseName || null,
      content_sha256: contentHash || null,
      reason,
    }),
    cache: "no-store",
  });
  if (response.status === 409) redirect("/admin?reference_error=duplicate");
  if (!response.ok) redirect("/admin?reference_error=create");
  revalidatePath("/admin");
  redirect("/admin?reference_updated=created");
}

async function reviewMedicalReference(formData: FormData) {
  "use server";
  const token = await requireAdminToken();
  const referenceId = String(formData.get("reference_id") ?? "");
  const expectedStatus = String(formData.get("expected_status") ?? "");
  const status = String(formData.get("status") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(referenceId) || !["draft", "in_review", "approved", "retired"].includes(expectedStatus) || !["draft", "in_review", "approved", "retired"].includes(status) || reason.length < 8 || reason.length > 1000) redirect("/admin?reference_error=invalid");
  const response = await fetch(`${API_BASE_URL}/admin/medical-references/${encodeURIComponent(referenceId)}/review`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ expected_status: expectedStatus, status, reason }),
    cache: "no-store",
  });
  if (response.status === 409) redirect("/admin?reference_error=stale");
  if (!response.ok) redirect("/admin?reference_error=review");
  revalidatePath("/admin");
  redirect("/admin?reference_updated=reviewed");
}
async function revokeReviewerScope(formData: FormData) {
  "use server";
  const token = await requireAdminToken();
  const scopeId = String(formData.get("scope_id") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(scopeId) || reason.length < 8 || reason.length > 1000) {
    redirect("/admin?scope_error=invalid");
  }
  const response = await fetch(
    `${API_BASE_URL}/admin/reviewer-scopes/${encodeURIComponent(scopeId)}/revoke`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ reason }),
      cache: "no-store",
    },
  );
  if (response.status === 409) redirect("/admin?scope_error=revoked");
  if (!response.ok) redirect("/admin?scope_error=revoke");
  revalidatePath("/admin");
  redirect("/admin?scope_updated=revoked");
}

type AdminPageProps = {
  searchParams: Promise<{
    scope_updated?: string;
    scope_error?: string;
    reference_updated?: string;
    reference_error?: string;
    reference_history?: string;
  }>;
};

export default async function AdminGovernancePage({ searchParams }: AdminPageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const user = session.user as { role?: string; display_name?: string | null };
  if (user.role !== "admin") redirect("/dashboard");

  const params = await searchParams;
  const token = await requireAdminToken();
  const referencesResponse = await fetch(`${API_BASE_URL}/admin/medical-references?limit=50`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    cache: "no-store",
  });
  const medicalReferences = referencesResponse.ok
    ? await referencesResponse.json() as Array<{
        id: string; title: string; publisher: string; url: string; evidence_type: string;
        version: string; review_status: string; next_review_due: string | null;
      }>
    : [];
  const historyId = params.reference_history ?? "";
  const historyResponse = /^[0-9a-f-]{36}$/i.test(historyId)
    ? await fetch(`${API_BASE_URL}/admin/medical-references/${encodeURIComponent(historyId)}/history`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
      })
    : null;
  const referenceHistory = historyResponse?.ok
    ? await historyResponse.json() as Array<{
        id: string; event_type: string; previous_status: string | null;
        new_status: string; reason: string; actor_id: string; created_at: string;
      }>
    : [];

  const [{ data, error }, scopeData] = await Promise.all([
    getGovernanceOverview(),
    getReviewerScopeGovernance(),
  ]);

  const referenceError = params.reference_error
    ? ({
        invalid: "Check the source metadata, URL and optional SHA-256 checksum.",
        duplicate: "A source with this URL and version already exists.",
        create: "The source record could not be created. Check the URL and metadata.",
        stale: "The source status changed. Refresh the page before reviewing it again.",
        review: "The source review decision could not be saved.",
      } as Record<string, string>)[params.reference_error] ?? "The source operation could not be completed."
    : null;

  const scopeError = params.scope_error
    ? ({
        invalid: "Check the reviewer, scope and reason. Reasons must contain at least eight characters.",
        duplicate: "This exact scope is already active for the selected reviewer.",
        grant: "The scope could not be granted. Confirm the reviewer is active and verified, and that the catalog key exists.",
        revoke: "The scope could not be revoked. Please try again.",
        revoked: "This scope has already been revoked.",
      } as Record<string, string>)[params.scope_error] ?? "The scope operation could not be completed."
    : null;

  return (
    <main id="main-content" className="admin-page">
      <section className="admin-hero">
        <div className="container">
          <Link className="back-link" href="/dashboard">← Back to workspace</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> ADMINISTRATION</div>
          <h1>Governance, <em>with accountability.</em></h1>
          <p>Monitor account roles, catalog review states and the operational history of reviewer access.</p>
          <div className="admin-identity">
            <span>ADMINISTRATOR</span>
            <strong>{user.display_name || "Administrator"}</strong>
          </div>
        </div>
      </section>

      <section className="container admin-content">
        {error && <div className="review-alert" role="alert">{error}</div>}
        {scopeData.error && <div className="review-alert" role="alert">{scopeData.error}</div>}
        {scopeError && <div className="review-alert" role="alert">{scopeError}</div>}
        {referenceError && <div className="review-alert" role="alert">{referenceError}</div>}
        {params.reference_updated && <div className="review-alert review-alert-success" role="status">Medical source metadata created as a draft.</div>}
        {params.scope_updated && (
          <div className="review-alert review-alert-success" role="status">
            Reviewer scope {params.scope_updated} successfully. The audit event has been recorded.
          </div>
        )}

        {data && (
          <>
            <div className="admin-section-heading">
              <div><span className="eyebrow">ACCESS OVERVIEW</span><h2>Account roles</h2></div>
              <span className="review-count">ACTIVE / INACTIVE</span>
            </div>
            <div className="admin-account-grid">
              {(["patient", "reviewer", "admin"] as const).map((role) => (
                <article className="admin-metric-card" key={role}>
                  <span>{role} accounts</span>
                  <strong>{data.accounts[role]?.active ?? 0}</strong>
                  <small>{data.accounts[role]?.inactive ?? 0} inactive</small>
                </article>
              ))}
            </div>

            <div className="admin-section-heading admin-subsection">
              <div><span className="eyebrow">CONTENT GOVERNANCE</span><h2>Catalog review status</h2></div>
            </div>
            <div className="admin-catalog-grid">
              {([
                ["Diseases", data.catalog.diseases],
                ["Symptoms", data.catalog.symptoms],
                ["Disease–symptom links", data.catalog.disease_symptom_links],
              ] as const).map(([label, counts]) => (
                <article className="admin-catalog-card" key={label}>
                  <div className="admin-catalog-title"><h3>{label}</h3><strong>{total(counts)}</strong></div>
                  <div className="admin-status-list">
                    {reviewStatuses.map((status) => (
                      <div key={status}><span>{statusLabel(status)}</span><strong>{counts[status] ?? 0}</strong></div>
                    ))}
                  </div>
                </article>
              ))}
            </div>

            <div className="admin-section-heading admin-subsection">
              <div><span className="eyebrow">ACCESS AUDIT</span><h2>Recent reviewer role changes</h2></div>
              <span className="review-count">{data.recent_role_changes.length} EVENTS</span>
            </div>
            {data.recent_role_changes.length === 0 ? (
              <div className="review-history-empty">No reviewer role changes have been recorded yet.</div>
            ) : (
              <div className="admin-event-list">
                {data.recent_role_changes.map((event) => (
                  <article className="admin-event-card" key={event.id}>
                    <div className="review-history-topline">
                      <strong>{event.previous_role} → {event.new_role}</strong>
                      <time dateTime={event.created_at}>{new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.created_at))}</time>
                    </div>
                    <p>{event.reason}</p>
                    <div className="admin-event-meta">
                      <span>Operator: {event.operator_identity}</span>
                      <span>Account reference: {event.target_user_id}</span>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </>
        )}

        <div className="admin-section-heading admin-subsection">
          <div><span className="eyebrow">REVIEWER ACCESS CONTROL</span><h2>Assign catalog responsibilities</h2></div>
        </div>
        <div className="admin-scope-layout">
          <form action={grantReviewerScope} className="admin-scope-form">
            <label>Verified reviewer account
              <select name="reviewer_id" required defaultValue="">
                <option value="" disabled>Select a reviewer</option>
                {scopeData.reviewers.map((reviewer) => (
                  <option value={reviewer.id} key={reviewer.id}>
                    {reviewer.display_name ? `${reviewer.display_name} — ${reviewer.email}` : reviewer.email}
                  </option>
                ))}
              </select>
            </label>
            <label>Catalog category
              <select name="scope_type" required defaultValue="disease">
                <option value="disease">Diseases</option>
                <option value="symptom">Symptoms</option>
                <option value="disease_symptom">Disease–symptom relationships</option>
              </select>
            </label>
            <label>Exact catalog key <span>(optional — leave blank for the entire category)</span>
              <input name="scope_key" maxLength={200} placeholder="e.g. DIS_CODE or DIS_CODE:SYM_CODE" />
            </label>
            <label>Reason for assignment
              <textarea name="reason" minLength={8} maxLength={1000} required rows={3} placeholder="Document why this reviewer needs this scope." />
            </label>
            <button type="submit" disabled={scopeData.reviewers.length === 0}>Grant review scope</button>
            {scopeData.reviewers.length === 0 && <small>No active, verified reviewer accounts are currently available.</small>}
            <p className="admin-scope-hint">A blank key grants access to every entry in the selected category. An exact key limits access to one disease code, symptom code, or relationship key formatted as DISEASE:SYMPTOM.</p>
          </form>

          <div className="admin-scope-list">
            <h3>Reviewer scope assignments</h3>
            {scopeData.scopes.length === 0 ? (
              <div className="review-history-empty">No reviewer scopes have been assigned yet.</div>
            ) : scopeData.scopes.map((scope) => (
              <article className="admin-scope-card" key={scope.id}>
                <div className="review-history-topline">
                  <strong>{scope.reviewer_email}</strong>
                  <span className={scope.revoked_at ? "admin-scope-revoked" : "admin-scope-active"}>
                    {scope.revoked_at ? "Revoked" : "Active"}
                  </span>
                </div>
                <p><strong>{scope.scope_type.replaceAll("_", " ")}</strong> · {scope.scope_key || "All entries in category"}</p>
                <small>Granted: {new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(scope.granted_at))}</small>
                <small>Reason: {scope.grant_reason}</small>
                {!scope.revoked_at && (
                  <form action={revokeReviewerScope} className="admin-revoke-form">
                    <input type="hidden" name="scope_id" value={scope.id} />
                    <label>Revocation reason
                      <input name="reason" minLength={8} maxLength={1000} required placeholder="Explain why access is ending" />
                    </label>
                    <button type="submit" className="admin-revoke-button">Revoke scope</button>
                  </form>
                )}
                {scope.revoked_at && scope.revoke_reason && <small>Revoked: {scope.revoke_reason}</small>}
              </article>
            ))}
          </div>
        </div>

        <div className="admin-section-heading admin-subsection">
          <div><span className="eyebrow">IMMUTABLE ACCESS HISTORY</span><h2>Scope grant and revocation events</h2></div>
          <span className="review-count">{scopeData.events.length} EVENTS</span>
        </div>
        {scopeData.events.length === 0 ? (
          <div className="review-history-empty">No scope changes have been recorded.</div>
        ) : (
          <div className="admin-event-list">
            {scopeData.events.map((event) => (
              <article className="admin-event-card" key={event.id}>
                <div className="review-history-topline">
                  <strong>{event.event_type} · {event.scope_type.replaceAll("_", " ")}</strong>
                  <time dateTime={event.created_at}>{new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.created_at))}</time>
                </div>
                <p>{event.scope_key || "All entries in category"} — {event.reason}</p>
                <div className="admin-event-meta">
                  <span>Reviewer account: {event.reviewer_id}</span>
                  <span>Administrator: {event.operator_id}</span>
                </div>
              </article>
            ))}
          </div>
        )}

        <div className="admin-section-heading admin-subsection">
          <div><span className="eyebrow">SOURCE PROVENANCE</span><h2>Medical reference registry</h2></div>
          <span className="review-count">{medicalReferences.length} RECORDS</span>
        </div>
        <div className="admin-scope-layout">
          <form action={createMedicalReference} className="admin-scope-form">
            <label>Source title<input name="title" minLength={3} maxLength={300} required placeholder="Publication or guideline title" /></label>
            <label>Publisher / organization<input name="publisher" minLength={2} maxLength={200} required placeholder="Issuing organization" /></label>
            <label>Source URL<input name="url" type="url" maxLength={1000} required placeholder="https://..." /></label>
            <label>Evidence type<input name="evidence_type" minLength={2} maxLength={80} required placeholder="Guideline, systematic review, official page..." /></label>
            <label>Version<input name="version" defaultValue="1" maxLength={80} required /></label>
            <label>Publication date<input name="published_on" type="date" /></label>
            <label>Accessed date<input name="accessed_on" type="date" /></label>
            <label>Next review due<input name="next_review_due" type="date" /></label>
            <label>License<input name="license_name" maxLength={200} placeholder="Optional license details" /></label>
            <label>Content SHA-256<input name="content_sha256" minLength={64} maxLength={64} pattern="[a-fA-F0-9]{64}" placeholder="Optional 64-character checksum" /></label>
            <label>Registration reason<textarea name="reason" minLength={8} maxLength={1000} required rows={3} placeholder="Why is this source being registered?" /></label>
            <button type="submit">Register source as draft</button>
            <p className="admin-scope-hint">New source records remain drafts. Registration does not approve the source or establish clinical validity.</p>
          </form>
          <div className="admin-scope-list">
            <h3>Registered sources</h3>
            {medicalReferences.length === 0 ? (
              <div className="review-history-empty">No medical source records have been registered.</div>
            ) : medicalReferences.map((source) => (
              <article className="admin-scope-card" key={source.id}>
                <div className="review-history-topline">
                  <strong>{source.title}</strong>
                  <span className={source.review_status === "approved" ? "admin-scope-active" : "admin-scope-revoked"}>{source.review_status.replaceAll("_", " ")}</span>
                </div>
                <p>{source.publisher} · {source.evidence_type} · Version {source.version}</p>
                <a href={source.url} target="_blank" rel="noopener noreferrer">{source.url}</a>
                {source.next_review_due && <small>Review due: {source.next_review_due}</small>}
                <form action={reviewMedicalReference} className="admin-revoke-form">
                  <input type="hidden" name="reference_id" value={source.id} />
                  <input type="hidden" name="expected_status" value={source.review_status} />
                  <label>Set source review state
                    <select name="status" defaultValue={source.review_status}>
                      <option value="draft">Draft</option>
                      <option value="in_review">In review</option>
                      <option value="approved">Approved</option>
                      <option value="retired">Retired</option>
                    </select>
                  </label>
                  <label>Review reason
                    <input name="reason" minLength={8} maxLength={1000} required placeholder="Document the source review decision" />
                  </label>
                  <button type="submit">Save source review state</button>
                </form>
                <Link href={"/admin?reference_history=" + encodeURIComponent(source.id)}>View source audit history</Link>
              </article>
            ))}
          </div>
        </div>

        {historyId && (
          <section className="admin-section-heading admin-subsection" aria-labelledby="source-history-title">
            <div><span className="eyebrow">SOURCE AUDIT TRAIL</span><h2 id="source-history-title">Medical reference history</h2></div>
            <span className="review-count">{referenceHistory.length} EVENTS</span>
          </section>
        )}
        {historyId && (
          referenceHistory.length > 0 ? (
            <div className="admin-event-list">
              {referenceHistory.map((event) => (
                <article className="admin-event-card" key={event.id}>
                  <div className="review-history-topline">
                    <strong>{event.event_type.replaceAll("_", " ")} · {event.previous_status ? event.previous_status + " → " : ""}{event.new_status}</strong>
                    <time dateTime={event.created_at}>{new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.created_at))}</time>
                  </div>
                  <p>{event.reason}</p>
                  <div className="admin-event-meta"><span>Actor account: {event.actor_id}</span></div>
                </article>
              ))}
            </div>
          ) : (
            <div className="review-history-empty">No source audit events were found for this reference.</div>
          )
        )}
        <div className="review-safety-note">
          <strong>Governance boundary</strong>
          <p>This page reports operational account and catalog review metadata only. It does not assess clinical evidence quality, certify reviewers, or establish that any medical content is clinically validated.</p>
        </div>
      </section>
    </main>
  );
}
