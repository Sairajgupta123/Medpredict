import Link from "next/link";

const modules = [
  {
    number: "01",
    title: "Symptom checker",
    description: "Describe symptoms in your own words. The guided analysis experience and evaluated model connection are being developed.",
    status: "Coming in a later milestone",
    icon: "✳",
  },
  {
    number: "02",
    title: "Skin image analysis",
    description: "A separate image workflow with supported-class boundaries, upload checks and uncertainty handling is in research.",
    status: "Research in progress",
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

export default function DashboardPage() {
  return (
    <main id="main-content" className="dashboard-page">
      <section className="dashboard-hero">
        <div className="container">
          <Link className="back-link" href="/">← Back to home</Link>
          <div className="eyebrow"><span className="eyebrow-dot" /> MEDIPREDICT WORKSPACE</div>
          <h1>Your health information,<br /><em>organized with care.</em></h1>
          <p>This workspace is under active development. The cards below show the planned modules and their current implementation stage.</p>
          <div className="workspace-notice"><span aria-hidden="true">i</span><div><strong>Preview environment</strong><small>Prediction, image upload and personalized medical guidance are not available in this frontend milestone.</small></div></div>
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
            </article>
          ))}
        </div>
      </section>
      <section className="container dashboard-bottom">
        <div><span className="eyebrow">A NOTE ON SAFETY</span><h2>Not a diagnosis.<br /><em>Always a reason to seek clarity.</em></h2></div>
        <p>MediPredict cannot determine whether you have a disease. If you have severe, rapidly worsening or worrying symptoms, seek appropriate medical care rather than waiting for this project to become available.</p>
      </section>
    </main>
  );
}
