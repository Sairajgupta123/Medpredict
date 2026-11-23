import Link from "next/link";
import { LogoutButton } from "@/components/logout-button";
import { getSessionUser } from "@/lib/auth-proxy";
import { apiRequest, type ResearchModelStatusResponse } from "@/lib/api";

const modules = [
  {
    number: "01",
    title: "Symptom checker",
    description: "Try a limited symptom phrase recognizer. It does not predict disease or interpret all medical context.",
    status: "Phrase review prototype available",
    icon: "✳",
  },
  {
    number: "02",
    title: "Skin image analysis",
    description: "Consent-first private image intake with separate processing, history and human-review permissions. No disease classification is performed.",
    status: "Private intake prototype available",
    icon: "◈",
  },
  {
    number: "03",
    title: "Health information",
    description: "General educational guidance will appear only after its sources, wording and review status meet publication requirements.",
    status: "No approved content yet",
    icon: "⌁",
  },
];

type SessionUser = {
  display_name?: string | null;
  email?: string;
  role?: string;
};

export default async function DashboardPage() {
  const session = await getSessionUser();
  const user = session.user as SessionUser | null;
  const modelStatus = await apiRequest<ResearchModelStatusResponse>("/models/status").catch(() => null);

  return (
    <main id="main-content" className="dashboard-page">
      <section className="dashboard-hero">
        <div className="container">
          <Link className="back-link" href="/">← Back to home</Link>
          <div className="dashboard-account-row">
            <div className="eyebrow"><span className="eyebrow-dot" /> MEDIPREDICT WORKSPACE</div>
            {user ? (
              <div className="account-chip">
                <span className="account-avatar" aria-hidden="true">{(user.display_name || user.email || "M").charAt(0).toUpperCase()}</span>
                <span className="account-identity"><strong>{user.display_name || "Your account"}</strong><small>{user.email}</small></span>
                {user.role === "reviewer" || user.role === "admin" ? (
                  <Link className="review-access-link" href="/review">Reviewer console ↗</Link>
                ) : null}
                {user.role === "admin" ? (
                  <Link className="review-access-link" href="/admin">Admin governance ↗</Link>
                ) : null}
                <LogoutButton />
              </div>
            ) : (
              <Link className="dashboard-signin" href="/login">Sign in to your account ↗</Link>
            )}
          </div>
          <h1>{user ? `Welcome, ${user.display_name || "back"}.` : "Your health information,"}<br /><em>organized with care.</em></h1>
          <p>This workspace is under active development. The cards below show the planned modules and their current implementation stage.</p>
          <div className="workspace-notice"><span aria-hidden="true">i</span><div><strong>{user ? "Signed-in workspace" : "Preview environment"}</strong><small>The symptom prototype recognizes phrases only; disease prediction, image analysis and personalized guidance are not available.</small></div></div>
        </div>
      </section>
      <section className="container dashboard-modules">
        <div className="dashboard-section-heading"><div><div className="eyebrow">YOUR WORKSPACE</div><h2>Explore the modules</h2></div><span className="module-count">03 MODULES</span></div>
        <div className="dashboard-grid">
          {modules.map((item) => (
            <article className="dashboard-card" key={item.number}>
              <div className="dashboard-card-top"><span>{item.number}</span><span className="workflow-icon">{item.icon}</span></div>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              <div className="dashboard-card-status"><span />{item.status}</div>
              {item.number === "01" && <Link className="module-action" href="/symptom-checker">Open prototype <span aria-hidden="true">→</span></Link>}{item.number === "02" && user && <><Link className="module-action" href="/skin-image">Open private intake <span aria-hidden="true">→</span></Link><Link className="module-action" href="/history/skin-images">View image history <span aria-hidden="true">→</span></Link></>}
            </article>
          ))}
        </div>
      </section>
      <section className="container dashboard-modules" aria-labelledby="model-status-heading">
        <div className="dashboard-section-heading">
          <div><div className="eyebrow">MODEL OPERATIONS</div><h2 id="model-status-heading">Research model configuration</h2></div>
          <span className="module-count">INFERENCE DISABLED</span>
        </div>
        <div className="dashboard-grid">
          {(["symptom_text", "skin_image"] as const).map((key) => {
            const model = modelStatus?.[key];
            const label = key === "symptom_text" ? "Symptom text model" : "Skin image model";
            const status = !modelStatus ? "Status service unavailable" :
              model?.status === "not_configured" ? "Artifact path not configured" :
              model?.status === "invalid_configuration" ? "Path configuration is invalid" :
              "Path configured; artifact not loaded";
            return (
              <article className="dashboard-card" key={key}>
                <div className="dashboard-card-top"><span>{key === "symptom_text" ? "TEXT" : "IMAGE"}</span><span className="workflow-icon">◌</span></div>
                <h3>{label}</h3>
                <p>{status}. This status does not verify artifact existence, trust or model quality.</p>
                <div className="dashboard-card-status"><span />Research-only · inference disabled</div>
              </article>
            );
          })}
        </div>
        <p role="note">These indicators report configuration only. MediPredict does not load these models or provide disease predictions or clinical diagnoses.</p>
      </section>
      <section className="container dashboard-bottom">
        <div><span className="eyebrow">A NOTE ON SAFETY</span><h2>Not a diagnosis.<br /><em>Always a reason to seek clarity.</em></h2></div>
        <p>MediPredict cannot determine whether you have a disease. If you have severe, rapidly worsening or worrying symptoms, seek appropriate medical care rather than waiting for this project to become available.</p>
      </section>
    </main>
  );
}
