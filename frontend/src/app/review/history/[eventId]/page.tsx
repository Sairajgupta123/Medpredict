import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { getReviewedCatalogEntry, getSessionUser } from "@/lib/auth-proxy";

type ReviewedEntryPageProps = {
  params: Promise<{ eventId: string }>;
};

export default async function ReviewedEntryPage({ params }: ReviewedEntryPageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const user = session.user as { role?: string };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");

  const { eventId } = await params;
  const { data, error } = await getReviewedCatalogEntry(eventId);
  if (!data && error?.includes("not part of your review history")) notFound();

  return (
    <main id="main-content" className="review-page">
      <section className="review-hero review-entry-hero">
        <div className="container">
          <Link className="back-link" href="/review#review-history-title">← Back to review history</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> CATALOG GOVERNANCE</div>
          <h1>Reviewed catalog <em>entry.</em></h1>
          <p>Inspect the current catalog record alongside the immutable decision that brought you here.</p>
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
                <span className={`review-status review-status-${data.entry.status}`}>{data.entry.status.replaceAll("_", " ")}</span>
              </div>
              {data.entry.description && <p className="review-description">{data.entry.description}</p>}
              {data.entry.relevance_weight !== null && (
                <div className="review-item-meta">
                  <span>Relationship relevance weight</span>
                  <strong>{data.entry.relevance_weight}</strong>
                </div>
              )}
              {data.entry.created_at && (
                <div className="review-item-meta">
                  <span>Catalog entry created</span>
                  <time dateTime={data.entry.created_at}>
                    {new Intl.DateTimeFormat("en-IN", { dateStyle: "long" }).format(new Date(data.entry.created_at))}
                  </time>
                </div>
              )}
            </article>

            <section className="review-entry-audit" aria-labelledby="entry-audit-title">
              <div className="review-section-heading">
                <div>
                  <span className="eyebrow">IMMUTABLE AUDIT RECORD</span>
                  <h2 id="entry-audit-title">Decision details</h2>
                </div>
                <span className="review-count">RECORDED EVENT</span>
              </div>
              <article className="review-history-card">
                <div className="review-history-topline">
                  <span className="review-type">{data.event.target_type.replaceAll("_", " ")}</span>
                  <time dateTime={data.event.created_at}>
                    {new Intl.DateTimeFormat("en-IN", { dateStyle: "long", timeStyle: "short" }).format(new Date(data.event.created_at))}
                  </time>
                </div>
                <div className="review-history-change">
                  <strong>{data.event.target_key}</strong>
                  <span>{data.event.previous_status.replaceAll("_", " ")} <span aria-hidden="true">→</span> {data.event.new_status.replaceAll("_", " ")}</span>
                </div>
                <p>{data.event.reason}</p>
                <small>Reviewer ID: {data.event.reviewer_id}</small>
              </article>
            </section>
          </>
        )}
        <div className="review-safety-note">
          <strong>Review boundary</strong>
          <p>This record documents a catalog-governance decision. It is not evidence of clinical validity, diagnosis, or treatment suitability.</p>
        </div>
      </section>
    </main>
  );
}
