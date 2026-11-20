import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { getPendingCatalogEntry, getSessionUser } from "@/lib/auth-proxy";

type PendingEntryPageProps = {
  searchParams: Promise<{ type?: string; key?: string }>;
};

export default async function PendingEntryPage({ searchParams }: PendingEntryPageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const user = session.user as { role?: string };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");

  const params = await searchParams;
  const targetType = params.type ?? "";
  const targetKey = params.key ?? "";
  const { data, error } = await getPendingCatalogEntry(targetType, targetKey);
  if (!data && error === "This pending catalog entry is unavailable.") notFound();

  return (
    <main id="main-content" className="review-page">
      <section className="review-hero review-entry-hero">
        <div className="container">
          <Link className="back-link" href="/review">← Back to review queue</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> CATALOG GOVERNANCE</div>
          <h1>Inspect before <em>deciding.</em></h1>
          <p>Review the catalog record, its linked entries and the limits of the available source evidence before recording a decision.</p>
        </div>
      </section>
      <section className="container review-content">
        {error && <div className="review-alert" role="alert">{error}</div>}
        {data && (
          <>
            <article className="review-card review-entry-card">
              <div className="review-card-heading">
                <div>
                  <span className="review-type">{data.entry.target_type.replaceAll("_", " ")}</span>
                  <h2>{data.entry.name}</h2>
                  <p className="review-key">{data.entry.target_key}</p>
                </div>
                <span className={`review-status review-status-${data.entry.status}`}>
                  {data.entry.status.replaceAll("_", " ")}
                </span>
              </div>
              {data.entry.description ? (
                <p className="review-description">{data.entry.description}</p>
              ) : (
                <p className="review-assignment-empty">No description is recorded for this entry.</p>
              )}
              <div className="review-item-meta">
                <span>Active in catalog: <strong>{data.entry.is_active ? "Yes" : "No"}</strong></span>
                {data.entry.created_at && (
                  <span>Created {new Intl.DateTimeFormat("en-IN", { dateStyle: "long" }).format(new Date(data.entry.created_at))}</span>
                )}
                {data.entry.relevance_weight !== null && (
                  <span>Relationship relevance weight: <strong>{data.entry.relevance_weight}</strong></span>
                )}
              </div>
              {data.entry.related_entries.length > 0 && (
                <section className="review-entry-audit" aria-labelledby="related-entry-title">
                  <div className="review-section-heading">
                    <div><span className="eyebrow">RELATIONSHIP CONTEXT</span><h2 id="related-entry-title">Linked catalog entries</h2></div>
                  </div>
                  <ul className="review-assignment-list">
                    {data.entry.related_entries.map((related) => (
                      <li key={`${related.target_type}:${related.target_key}`}>
                        <span className="review-assignment-type">{related.target_type}</span>
                        <strong>{related.name}</strong>
                        <small>{related.target_key} · {related.status.replaceAll("_", " ")}</small>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </article>

            <section className="review-entry-audit" aria-labelledby="evidence-title">
              <div className="review-section-heading">
                <div><span className="eyebrow">SOURCE TRACEABILITY</span><h2 id="evidence-title">Reference evidence</h2></div>
                <span className="review-count">{data.evidence.references.length} ATTACHED REFERENCES</span>
              </div>
              {data.evidence.references.length > 0 ? (
                <ul className="review-assignment-list">
                  {data.evidence.references.map((reference, index) => (
                    <li key={`${reference.url}:${index}`}>
                      <strong><a href={reference.url} target="_blank" rel="noopener noreferrer">{reference.title}</a></strong>
                      {reference.source && <small>{reference.source}</small>}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="review-alert" role="status">
                  <strong>References are not attached in the current catalog schema.</strong>
                  <p>{data.evidence.message}</p>
                </div>
              )}
            </section>

            <div className="review-safety-note">
              <strong>Research-only review boundary</strong>
              <p>A catalog description, relationship weight, or reviewer decision is not proof of clinical validity. Verify appropriate authoritative sources independently. This application is not a diagnostic or treatment system.</p>
            </div>
            <div className="review-filter-actions">
              <Link className="button button-primary" href="/review">Return to queue and record a decision</Link>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
