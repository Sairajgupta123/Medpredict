import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import {
  attachCatalogReference,
  getPendingCatalogEntry,
  getReviewableMedicalReferences,
  getSessionUser,
  removeCatalogReference,
} from "@/lib/auth-proxy";

type PendingEntryPageProps = {
  searchParams: Promise<{
    type?: string;
    key?: string;
    source_updated?: string;
    source_error?: string;
  }>;
};

async function attachSourceAction(formData: FormData) {
  "use server";
  const type = String(formData.get("target_type") ?? "");
  const key = String(formData.get("target_key") ?? "");
  const referenceId = String(formData.get("reference_id") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!type || !key || !referenceId || reason.length < 8 || reason.length > 1000) {
    redirect(`/review/entry?type=${encodeURIComponent(type)}&key=${encodeURIComponent(key)}&source_error=invalid`);
  }
  const result = await attachCatalogReference(type, key, referenceId, reason);
  if (result.error) {
    redirect(`/review/entry?type=${encodeURIComponent(type)}&key=${encodeURIComponent(key)}&source_error=attach`);
  }
  revalidatePath("/review/entry");
  redirect(`/review/entry?type=${encodeURIComponent(type)}&key=${encodeURIComponent(key)}&source_updated=linked`);
}

async function removeSourceAction(formData: FormData) {
  "use server";
  const type = String(formData.get("target_type") ?? "");
  const key = String(formData.get("target_key") ?? "");
  const linkId = String(formData.get("link_id") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!linkId || reason.length < 8 || reason.length > 1000) {
    redirect(`/review/entry?type=${encodeURIComponent(type)}&key=${encodeURIComponent(key)}&source_error=invalid`);
  }
  const result = await removeCatalogReference(linkId, reason);
  if (result.error) {
    redirect(`/review/entry?type=${encodeURIComponent(type)}&key=${encodeURIComponent(key)}&source_error=remove`);
  }
  revalidatePath("/review/entry");
  redirect(`/review/entry?type=${encodeURIComponent(type)}&key=${encodeURIComponent(key)}&source_updated=removed`);
}

export default async function PendingEntryPage({ searchParams }: PendingEntryPageProps) {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const user = session.user as { role?: string };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");

  const params = await searchParams;
  const targetType = params.type ?? "";
  const targetKey = params.key ?? "";
  const [{ data, error }, sourceRegistry] = await Promise.all([
    getPendingCatalogEntry(targetType, targetKey),
    getReviewableMedicalReferences(),
  ]);
  if (!data && error === "This pending catalog entry is unavailable.") notFound();

  const attachedIds = new Set(data?.evidence.references.map((reference) => reference.reference_id) ?? []);
  const availableSources = sourceRegistry.items.filter((source) => !attachedIds.has(source.id));
  const sourceError = params.source_error
    ? ({
        invalid: "Enter a reason of at least eight characters.",
        attach: "The source could not be attached. Check your assignment and the source record.",
        remove: "The source link could not be removed. It may already have changed.",
      } as Record<string, string>)[params.source_error] ?? "The source action could not be completed."
    : null;

  return (
    <main id="main-content" className="review-page">
      <section className="review-hero review-entry-hero">
        <div className="container">
          <Link className="back-link" href="/review">← Back to review queue</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> CATALOG GOVERNANCE</div>
          <h1>Inspect before <em>deciding.</em></h1>
          <p>Review the catalog record, its linked entries and the provenance and review state of each attached source.</p>
        </div>
      </section>
      <section className="container review-content">
        {error && <div className="review-alert" role="alert">{error}</div>}
        {sourceRegistry.error && <div className="review-alert" role="alert">{sourceRegistry.error}</div>}
        {sourceError && <div className="review-alert" role="alert">{sourceError}</div>}
        {params.source_updated && (
          <div className="review-alert review-alert-success" role="status">
            Source link {params.source_updated} successfully. The action was recorded in the audit history.
          </div>
        )}
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
                <div><span className="eyebrow">SOURCE TRACEABILITY</span><h2 id="evidence-title">Attached references</h2></div>
                <span className="review-count">{data.evidence.references.length} ATTACHED</span>
              </div>
              {data.evidence.references.length > 0 ? (
                <ul className="review-assignment-list">
                  {data.evidence.references.map((reference) => (
                    <li key={reference.id}>
                      <strong><a href={reference.url} target="_blank" rel="noopener noreferrer">{reference.title}</a></strong>
                      <small>{reference.publisher} · {reference.evidence_type} · Version {reference.version}</small>
                      <small>Source review status: <strong>{reference.review_status.replaceAll("_", " ")}</strong></small>
                      {reference.published_on && <small>Published: {reference.published_on}</small>}
                      {reference.next_review_due && <small>Source review due: {reference.next_review_due}</small>}
                      <small>Link reason: {reference.link_reason}</small>
                      <form action={removeSourceAction} className="review-form">
                        <input type="hidden" name="target_type" value={targetType} />
                        <input type="hidden" name="target_key" value={targetKey} />
                        <input type="hidden" name="link_id" value={reference.id} />
                        <label>Reason for removing this link
                          <input name="reason" minLength={8} maxLength={1000} required placeholder="Explain why this source no longer applies" />
                        </label>
                        <button type="submit" className="admin-revoke-button">Remove source link</button>
                      </form>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="review-alert" role="status">
                  <strong>No source references are attached yet.</strong>
                </div>
              )}
              <p className="review-assignment-empty">{data.evidence.message}</p>
            </section>

            <section className="review-entry-audit" aria-labelledby="add-reference-title">
              <div className="review-section-heading">
                <div><span className="eyebrow">SOURCE REGISTRY</span><h2 id="add-reference-title">Attach an existing source</h2></div>
                <span className="review-count">{availableSources.length} AVAILABLE</span>
              </div>
              {availableSources.length === 0 ? (
                <div className="review-history-empty">
                  No unattached source records are available. An administrator can add source metadata from the medical reference registry.
                </div>
              ) : (
                <ul className="review-assignment-list">
                  {availableSources.map((source) => (
                    <li key={source.id}>
                      <strong><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></strong>
                      <small>{source.publisher} · {source.evidence_type} · Version {source.version}</small>
                      <small>Source review status: <strong>{source.review_status.replaceAll("_", " ")}</strong></small>
                      <form action={attachSourceAction} className="review-form">
                        <input type="hidden" name="target_type" value={targetType} />
                        <input type="hidden" name="target_key" value={targetKey} />
                        <input type="hidden" name="reference_id" value={source.id} />
                        <label>Reason for linking this source
                          <input name="reason" minLength={8} maxLength={1000} required placeholder="Explain its relevance to this catalog entry" />
                        </label>
                        <button type="submit">Attach source</button>
                      </form>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <div className="review-safety-note">
              <strong>Research-only review boundary</strong>
              <p>Source attachment records provenance, not proof of clinical validity. Draft, in-review, retired or overdue sources must not be treated as approved evidence. Verify authoritative sources independently. This application is not a diagnostic or treatment system.</p>
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
