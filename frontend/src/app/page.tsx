import Link from "next/link";

const workflows = [
  {
    number: "01",
    title: "Symptom understanding",
    description:
      "A limited English phrase recognizer organizes selected symptom mentions for your review. It does not predict diseases or assess medical urgency.",
    status: "Limited phrase prototype available",
    icon: "✳",
  },
  {
    number: "02",
    title: "Skin image research",
    description:
      "A consent-first private image intake prototype is available. Disease classification remains disabled until a dataset and model pass independent review.",
    status: "Research stage",
    icon: "◈",
  },
  {
    number: "03",
    title: "Reviewed health guidance",
    description:
      "A source-approval and review foundation is being built. No health recommendations are currently published.",
    status: "Review foundation in development",
    icon: "⌁",
  },
];

export default function HomePage() {
  return (
    <main id="main-content">
      <section className="hero-section">
        <div className="hero-orb hero-orb-one" aria-hidden="true" />
        <div className="hero-orb hero-orb-two" aria-hidden="true" />
        <div className="container hero-grid">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-dot" /> HEALTH INFORMATION RESEARCH PROTOTYPE</div>
            <h1>Understand health information. <em>Make informed next steps.</em></h1>
            <p className="hero-description">
              MediPredict is an academic project building separate symptom-input and private skin-image
              intake workflows. Disease prediction and personalized medical guidance are not currently available.
            </p>
            <div className="hero-actions">
              <Link className="button button-primary" href="/dashboard">Explore the workspace <span aria-hidden="true">→</span></Link>
              <a className="button button-secondary" href="#how-it-works">See how it works</a>
            </div>
            <div className="hero-note"><span aria-hidden="true">✦</span> Built around transparency, privacy and human oversight.</div>
          </div>
          <div className="hero-visual" aria-label="Illustration of a health information dashboard">
            <div className="visual-glow" />
            <div className="visual-card visual-card-main">
              <div className="visual-card-top"><span className="mini-mark">M</span><span>YOUR HEALTH OVERVIEW</span><span className="live-dot" /></div>
              <div className="visual-title">A clearer picture,<br /><strong>one step at a time.</strong></div>
              <div className="visual-line visual-line-wide" />
              <div className="visual-line visual-line-short" />
              <div className="visual-divider" />
              <div className="visual-metric-row">
                <div className="metric-icon">✳</div>
                <div><strong>Symptom analysis</strong><small>Structured information</small></div>
                <span className="metric-arrow">↗</span>
              </div>
              <div className="visual-metric-row">
                <div className="metric-icon metric-icon-mint">◈</div>
                <div><strong>Image research</strong><small>Separate model workflow</small></div>
                <span className="metric-arrow">↗</span>
              </div>
              <div className="visual-footer"><span /> EDUCATIONAL PROTOTYPE · NOT A DIAGNOSIS</div>
            </div>
            <div className="floating-chip chip-top"><span>✦</span> Evidence-aware design</div>
            <div className="floating-chip chip-bottom"><span>✓</span> Human review matters</div>
            <div className="visual-spark spark-one">✳</div>
            <div className="visual-spark spark-two">✧</div>
          </div>
        </div>
        <div className="container hero-bottom">
          <span>DESIGNED FOR CLARITY</span><span className="hero-bottom-line" /><span>ACADEMIC AI & HEALTHCARE PROJECT</span>
        </div>
      </section>

      <section className="section workflow-section" id="how-it-works">
        <div className="container">
          <div className="section-heading">
            <div>
              <div className="eyebrow">THE MEDIPREDICT APPROACH</div>
              <h2>Three distinct workstreams.<br /><em>One responsible approach.</em></h2>
            </div>
            <p>Each workstream has a separate implementation status. Current prototypes are clearly labeled and are not substitutes for professional care.</p>
          </div>
          <div className="workflow-grid">
            {workflows.map((item) => (
              <article className="workflow-card" key={item.number}>
                <div className="workflow-card-top"><span>{item.number}</span><span className="workflow-icon">{item.icon}</span></div>
                <h3>{item.title}</h3>
                <p>{item.description}</p>
                <div className="workflow-status"><span />{item.status}</div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section principles-section" id="our-approach">
        <div className="container principles-panel">
          <div className="principles-copy">
            <div className="eyebrow eyebrow-light">OUR COMMITMENT</div>
            <h2>Technology should inform, <em>not overpromise.</em></h2>
            <p>Health decisions deserve context, careful language and qualified human support. That principle shapes every part of this project.</p>
            <Link className="text-link text-link-light" href="/dashboard">View project workspace <span aria-hidden="true">→</span></Link>
          </div>
          <div className="principle-list">
            <div><span>01</span><p><strong>Clear uncertainty</strong><small>Model outputs will show limitations and avoid unsupported certainty.</small></p></div>
            <div><span>02</span><p><strong>Traceable information</strong><small>Published guidance requires reviewed sources and accountable approval.</small></p></div>
            <div><span>03</span><p><strong>Privacy by design</strong><small>Collect only what is necessary and protect sensitive information.</small></p></div>
          </div>
        </div>
      </section>

      <section className="safety-strip">
        <div className="container safety-inner">
          <span className="safety-icon" aria-hidden="true">i</span>
          <p><strong>Important:</strong> MediPredict is an academic prototype, not a medical device or diagnostic service. Do not use it to self-diagnose, delay urgent care, or change treatment. For health concerns, consult a qualified healthcare professional.</p>
        </div>
      </section>
    </main>
  );
}
