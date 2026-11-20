"use client";

import { FormEvent, useState } from "react";

type SymptomItem = {
  id: string;
  label: string;
  category: string;
};

type ContextualMention = SymptomItem & {
  context_flag: string;
};

type NormalizeResult = {
  taxonomy_version: string;
  matched_symptoms: SymptomItem[];
  contextual_mentions: ContextualMention[];
  unrecognized_text_present: boolean;
  review_required: boolean;
  clinical_interpretation_performed: false;
  disclaimer: string;
};

const contextLabels: Record<string, string> = {
  negated_or_denied_context: "Mentioned as absent or denied",
  possibly_historical_context: "May refer to an earlier symptom",
  uncertain_context: "Uncertain wording — please review",
  explicit_mention_unresolved: "Context needs review",
};

export function SymptomChecker() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<NormalizeResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setResult(null);
    setLoading(true);
    try {
      const response = await fetch("/api/symptoms/normalize", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ text }),
      });
      const body = await response.json() as NormalizeResult & { detail?: string };
      if (!response.ok) {
        setError(body.detail ?? "We could not process this text. Please try again.");
        return;
      }
      setResult(body);
    } catch {
      setError("Unable to connect to MediPredict. Please try again later.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="symptom-workspace">
      <div className="symptom-intro">
        <div className="eyebrow"><span className="eyebrow-dot" /> TEXT INPUT · RESEARCH PROTOTYPE</div>
        <h1>Tell us what <em>you are experiencing.</em></h1>
        <p>Describe symptoms in your own words. This first version only recognizes a limited vocabulary of phrases. It does not identify a disease or assess how serious a condition may be.</p>
      </div>

      <form className="symptom-form" onSubmit={handleSubmit}>
        <label className="field-label" htmlFor="symptom-description">
          Your symptom description
          <textarea
            id="symptom-description"
            maxLength={4000}
            onChange={(event) => setText(event.target.value)}
            placeholder="For example: I have a headache and fever since yesterday..."
            required
            rows={6}
            value={text}
          />
        </label>
        <div className="symptom-form-meta"><span>Your text is processed for this request and is not saved to prediction history.</span><span>{text.length}/4000</span></div>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="button button-primary symptom-submit" disabled={loading || !text.trim()} type="submit">
          {loading ? "Reviewing phrases..." : "Review symptom phrases"} <span aria-hidden="true">→</span>
        </button>
      </form>

      {result && (
        <section className="symptom-result" aria-live="polite">
          <div className="symptom-result-heading">
            <div><div className="eyebrow">TEXT REVIEW COMPLETE</div><h2>Recognized phrases</h2></div>
            <span className="review-pill">Human review required</span>
          </div>
          {result.matched_symptoms.length > 0 ? (
            <div className="recognized-list">
              {result.matched_symptoms.map((item) => (
                <div className="recognized-item" key={item.id}><span className="recognized-check">✓</span><strong>{item.label}</strong><small>{item.category}</small></div>
              ))}
            </div>
          ) : (
            <p className="symptom-empty">No supported symptom phrases were confidently recognized from this limited vocabulary. This does not mean that no symptoms are present.</p>
          )}

          {result.contextual_mentions.length > 0 && (
            <div className="context-review">
              <h3>Mentions that need your review</h3>
              {result.contextual_mentions.map((item, index) => (
                <div className="context-item" key={`${item.id}-${index}`}>
                  <strong>{item.label}</strong><span>{contextLabels[item.context_flag] ?? "Context needs review"}</span>
                </div>
              ))}
            </div>
          )}

          {result.unrecognized_text_present && <p className="symptom-empty">Some or all of your wording was outside the supported vocabulary. Please do not rely on this tool to interpret it.</p>}
          <div className="non-diagnostic-note"><strong>No disease prediction was performed.</strong><p>{result.disclaimer}</p><small>Vocabulary version {result.taxonomy_version}</small></div>
        </section>
      )}

      <aside className="symptom-safety">
        <span aria-hidden="true">!</span>
        <div><strong>When to seek help</strong><p>If symptoms are severe, rapidly worsening, or you are worried about your health, seek urgent advice from a qualified healthcare professional. Do not wait for this tool or use it to decide whether care is necessary.</p></div>
      </aside>
    </div>
  );
}
