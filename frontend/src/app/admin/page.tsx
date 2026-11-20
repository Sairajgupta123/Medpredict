import Link from "next/link";
import { redirect } from "next/navigation";
import { getGovernanceOverview, getSessionUser } from "@/lib/auth-proxy";

const reviewStatuses = ["draft", "in_review", "approved", "retired"] as const;

function total(values: Record<string, number>) {
  return Object.values(values).reduce((sum, value) => sum + value, 0);
}

function statusLabel(status: string) {
  return status.replace("_", " ");
}

export default async function AdminGovernancePage() {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const user = session.user as { role?: string; display_name?: string | null };
  if (user.role !== "admin") redirect("/dashboard");

  const { data, error } = await getGovernanceOverview();

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
        <div className="review-safety-note">
          <strong>Governance boundary</strong>
          <p>This page reports operational account and catalog review metadata only. It does not assess clinical evidence quality, certify reviewers, or establish that any medical content is clinically validated.</p>
        </div>
      </section>
    </main>
  );
}
