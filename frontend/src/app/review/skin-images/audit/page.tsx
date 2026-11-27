import Link from "next/link";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { API_BASE_URL, getSessionUser, SESSION_COOKIE } from "@/lib/auth-proxy";

type AuditEvent = {
  event_id: string;
  prediction_id: string;
  event_type: "assigned" | "unassigned" | "reassigned" | "image_accessed" | "reviewed";
  actor_id: string;
  actor_identity: string | null;
  actor_role: string;
  assigned_reviewer_id: string | null;
  outcome: string | null;
  reason: string;
  created_at: string;
};

function isAuditEvent(value: unknown): value is AuditEvent {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  return typeof event.event_id === "string" && uuid.test(event.event_id)
    && typeof event.prediction_id === "string" && uuid.test(event.prediction_id)
    && ["assigned", "unassigned", "reassigned", "image_accessed", "reviewed"].includes(String(event.event_type))
    && typeof event.actor_id === "string" && uuid.test(event.actor_id)
    && (event.actor_identity === null || (typeof event.actor_identity === "string" && event.actor_identity.length <= 320))
    // Audit events can be performed by patients (for example, consent withdrawal),
    // and a reviewer account may later be deactivated back to the patient role.
    && typeof event.actor_role === "string" && ["admin", "reviewer", "patient"].includes(event.actor_role)
    && (event.assigned_reviewer_id === null || (typeof event.assigned_reviewer_id === "string" && uuid.test(event.assigned_reviewer_id)))
    && (event.outcome === null || (typeof event.outcome === "string" && event.outcome.length <= 80))
    && typeof event.reason === "string" && event.reason.length <= 1000
    && typeof event.created_at === "string" && Number.isFinite(Date.parse(event.created_at));
}

const PAGE_SIZE = 200;

const EVENT_LABELS: Record<AuditEvent["event_type"], string> = {
  assigned: "Image assigned",
  unassigned: "Image assignment cleared",
  reassigned: "Image reassigned",
  image_accessed: "Private image accessed",
  reviewed: "Technical review submitted",
};

type PageProps = { searchParams: Promise<{ page?: string }> };

export default async function SkinImageAuditPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const parsedPage = Number(params.page ?? "0");
  const page = Number.isSafeInteger(parsedPage) && parsedPage >= 0 && parsedPage <= 50
    ? parsedPage
    : 0;
  const offset = page * PAGE_SIZE;
  const session = await getSessionUser();
  if (!session.user) redirect("/login");
  const user = session.user as { role?: string };
  if (user.role !== "reviewer" && user.role !== "admin") redirect("/dashboard");

  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) redirect("/login");

  let events: AuditEvent[] = [];
  let error = "";
  try {
    const response = await fetch(
      `${API_BASE_URL}/skin-images/review/audit?limit=${PAGE_SIZE}&offset=${offset}`,
      {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(8_000),
      },
    );
    if (response.ok) {
      const payload = await response.json();
      if (Array.isArray(payload) && payload.every(isAuditEvent)) events = payload;
      else error = "The audit service returned an unexpected response.";
    } else {
      error = response.status === 403
        ? "Your account does not have image-review audit access."
        : "The image-review audit history could not be loaded.";
    }
  } catch {
    error = "The MediPredict server is unavailable.";
  }

  return (
    <main id="main-content" className="review-page skin-audit-page">
      <section className="review-hero">
        <div className="container">
          <Link className="back-link" href="/review/skin-images">← Back to skin-image queue</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> SKIN IMAGE GOVERNANCE</div>
          <h1>Access and review <em>audit trail.</em></h1>
          <p>Every recorded assignment, unassignment, reassignment, private image retrieval and technical review is shown with the actor role and timestamp. Actor identity is restricted in reviewer views and available to administrators. This page contains audit metadata only, never image content or storage keys.</p>
          <div className="review-summary">
            <div><strong>{events.length.toString().padStart(2, "0")}</strong><span>EVENTS IN THIS VIEW</span></div>
            <div><strong>{user.role === "admin" ? "All image reviews" : "Your review activity"}</strong><span>AUTHORIZED AUDIT SCOPE</span></div>
          </div>
        </div>
      </section>

      <section className="container review-content">
        {error && <div className="review-alert" role="alert">{error}</div>}
        <div className="review-section-heading">
          <div><span className="eyebrow">IMMUTABLE EVENT RECORDS</span><h2>Recent activity</h2></div>
          <span className="review-count">{events.length} EVENTS · PAGE {page + 1}</span>
        </div>
        {!error && events.length === 0 ? (
          <div className="review-empty"><h3>No audit events are available</h3><p>Assignment, private image access and technical review events will appear here when recorded.</p></div>
        ) : (
          <div className="review-list">
            {events.map((event) => (
              <article className="review-card skin-audit-card" key={event.event_id}>
                <div className="review-card-heading">
                  <div>
                    <span className="review-type">{event.event_type.replaceAll("_", " ")}</span>
                    <h3>{EVENT_LABELS[event.event_type] ?? "Image review event"}</h3>
                    <p className="review-key">Submission reference: {event.prediction_id}</p>
                  </div>
                  <span className="review-status review-status-assigned">{event.actor_role}</span>
                </div>
                <div className="skin-audit-grid">
                  <div><span>Actor</span><strong>{event.actor_identity ?? "Identity restricted"}</strong></div>
                  <div><span>Recorded at</span><strong>{new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date(event.created_at))} IST</strong></div>
                  <div><span>Assigned reviewer</span><strong>{event.assigned_reviewer_id ?? "Not applicable"}</strong></div>
                  {event.outcome && <div><span>Outcome</span><strong>{event.outcome.replaceAll("_", " ")}</strong></div>}
                </div>
                <div className="skin-audit-reason"><span>Recorded reason</span><p>{event.reason}</p></div>
              </article>
            ))}
          </div>
        )}
        {!error && (
          <nav className="review-filter-actions" aria-label="Audit history pagination">
            {page > 0 && <Link className="button button-secondary" href={`/review/skin-images/audit?page=${page - 1}`}>← Newer events</Link>}
            {events.length === PAGE_SIZE && page < 50 && <Link className="button button-primary" href={`/review/skin-images/audit?page=${page + 1}`}>Older events →</Link>}
          </nav>
        )}
        <div className="review-safety-note">
          <strong>Audit interpretation</strong>
          <p>An image-access event is recorded after the backend successfully retrieves and validates the private image. It records a server-side retrieval, not proof that a person viewed every pixel. Browser caching is disabled for these responses. Audit records are operational evidence and do not establish clinical validity.</p>
        </div>
      </section>
    </main>
  );
}
