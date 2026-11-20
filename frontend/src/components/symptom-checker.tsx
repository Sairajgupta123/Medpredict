"use client";

import { FormEvent, useEffect, useState } from "react";

type Duration = "less_than_24_hours" | "one_to_three_days" | "four_to_seven_days" | "more_than_one_week" | "not_sure";
type Severity = "mild" | "moderate" | "severe" | "not_sure";
type Onset = "sudden" | "gradual" | "comes_and_goes" | "not_sure";

type SymptomItem = { id: string; label: string; category: string };
type ContextualMention = SymptomItem & { context_flag: string };
type ReportedContext = { duration: Duration; severity: Severity; onset: Onset };
type ReviewStatus = "present" | "not_present" | "unsure";
type NormalizeResult = {
  taxonomy_version: string;
  matched_symptoms: SymptomItem[];
  contextual_mentions: ContextualMention[];
  unrecognized_text_present: boolean;
  review_required: boolean;
  reported_context: ReportedContext;
  clinical_interpretation_performed: false;
  disclaimer: string;
};
type SymptomCatalog = {
  taxonomy_version: string;
  status: string;
  symptoms: SymptomItem[];
  disclaimer: string;
};

const contextLabels: Record<string, string> = {
  negated_or_denied_context: "Mentioned as absent or denied",
  possibly_historical_context: "May refer to an earlier symptom",
  uncertain_context: "Uncertain wording — please review",
  explicit_mention_unresolved: "Context needs review",
};

const categoryLabels: Record<string, string> = {
  pain: "Pain",
  general: "General",
  respiratory: "Respiratory",
  digestive: "Digestive",
  skin: "Skin",
  neurological: "Neurological",
};

export function SymptomChecker() {
  const [text, setText] = useState("");
  const [duration, setDuration] = useState<Duration>("not_sure");
  const [severity, setSeverity] = useState<Severity>("not_sure");
  const [onset, setOnset] = useState<Onset>("not_sure");
  const [result, setResult] = useState<NormalizeResult | null>(null);
  const [catalog, setCatalog] = useState<SymptomCatalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [reviewStatuses, setReviewStatuses] = useState<Record<string, ReviewStatus>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    fetch("/api/symptoms/catalog", { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(async (response) => {
        const body = await response.json() as SymptomCatalog & { detail?: string };
        if (!response.ok) throw new Error(body.detail ?? "Could not load the symptom list.");
        if (active) setCatalog(body);
      })
      .catch((cause: unknown) => {
        if (active) setCatalogError(cause instanceof Error ? cause.message : "Could not load the symptom list.");
      });
    return () => { active = false; };
  }, []);

  function addSymptom(item: SymptomItem) {
    setResult(null);
    setReviewStatuses({});
    setText((current) => {
      const sentence = current.trim();
      const addition = item.label.toLowerCase();
      if (!sentence) return `I am experiencing ${addition}.`;
      const withoutEnding = sentence.replace(/[.!?]+$/, "");
      return `${withoutEnding}, ${addition}.`;
    });
    setSelectedIds((current) => current.includes(item.id) ? current : [...current, item.id]);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setResult(null);
    setLoading(true);
    try {
      const response = await fetch("/api/symptoms/normalize", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          text,
          reported_context: { duration, severity, onset },
        }),
      });
      const body = await response.json() as NormalizeResult & { detail?: string };
      if (!response.ok) {
        setError(body.detail ?? "We could not process this information. Please try again.");
        return;
      }
      setResult(body);
      const reviewItems = [...body.matched_symptoms, ...body.contextual_mentions];
      setReviewStatuses(Object.fromEntries(reviewItems.map((item) => [item.id, "unsure" as ReviewStatus])));
    } catch {
      setError("Unable to connect to MediPredict. Please try again later.");
    } finally {
      setLoading(false);
    }
  }

  const reviewItems = result
    ? [...result.matched_symptoms, ...result.contextual_mentions]
    : [];
  const reviewCounts = reviewItems.reduce(
    (counts, item) => {
      const status = reviewStatuses[item.id] ?? "unsure";
      counts[status] += 1;
      return counts;
    },
    { present: 0, not_present: 0, unsure: 0 },
  );

  const groupedSymptoms = (catalog?.symptoms ?? []).reduce<Record<string, SymptomItem[]>>((groups, item) => {
    (groups[item.category] ??= []).push(item);
    return groups;
  }, {});

  return (
    <div className="symptom-workspace">
      <div className="symptom-intro">
        <div className="eyebrow"><span className="eyebrow-dot" /> TEXT INPUT · RESEARCH PROTOTYPE</div>
        <h1>Tell us what <em>you are experiencing.</em></h1>
        <p>Describe symptoms and, if you can, share when they started and how they feel. This prototype recognizes a limited vocabulary only; it does not identify a disease or assess medical urgency.</p>
      </div>

      <form className="symptom-form" onSubmit={handleSubmit}>
        <section className="symptom-catalog-picker" aria-labelledby="catalog-picker-title">
          <div className="catalog-picker-heading">
            <div><h2 id="catalog-picker-title">Choose from supported symptoms</h2><p>You can select terms to add them to your description, or write in your own words below.</p></div>
            {catalog && <span>{catalog.symptoms.length} terms</span>}
          </div>
          {catalogError && <p className="catalog-load-error" role="status">{catalogError} You can still enter a description manually.</p>}
          {!catalog && !catalogError && <p className="catalog-loading">Loading the supported symptom list…</p>}
          {catalog && Object.entries(groupedSymptoms).map(([category, items]) => (
            <div className="catalog-category" key={category}>
              <h3>{categoryLabels[category] ?? category}</h3>
              <div className="catalog-chip-list">
                {items.map((item) => {
                  const selected = selectedIds.includes(item.id);
                  return <button className={selected ? "catalog-chip selected" : "catalog-chip"} disabled={selected} key={item.id} onClick={() => addSymptom(item)} type="button" aria-pressed={selected}>{selected ? "✓ " : "+ "}{item.label}</button>;
                })}
              </div>
            </div>
          ))}
          {catalog && <small className="catalog-disclaimer">Vocabulary v{catalog.taxonomy_version} · {catalog.status.replaceAll("_", " ")}</small>}
        </section>

        <label className="field-label" htmlFor="symptom-description">
          Your symptom description
          <textarea
            id="symptom-description"
            maxLength={4000}
            onChange={(event) => {
              const nextText = event.target.value;
              setText(nextText);
              setResult(null);
              setReviewStatuses({});
              setSelectedIds((current) => current.filter((id) => {
                const selected = catalog?.symptoms.find((item) => item.id === id);
                return selected ? nextText.toLocaleLowerCase().includes(selected.label.toLocaleLowerCase()) : false;
              }));
            }}
            placeholder="For example: I have a headache and fever since yesterday..."
            required
            rows={6}
            value={text}
          />
        </label>
        <div className="symptom-form-meta"><span>Your text is processed for this request and is not saved to prediction history.</span><span>{text.length}/4000</span></div>

        <fieldset className="symptom-context-fields">
          <legend>About the symptoms you described</legend>
          <p className="context-helper">These are your own descriptions, not measurements or a medical assessment. Choose “Not sure” if you cannot tell.</p>
          <div className="context-fields-grid">
            <label className="field-label" htmlFor="symptom-duration">How long have you experienced them?
              <select id="symptom-duration" value={duration} onChange={(event) => { setDuration(event.target.value as Duration); setResult(null); setReviewStatuses({}); }}>
                <option value="not_sure">Not sure</option>
                <option value="less_than_24_hours">Less than 24 hours</option>
                <option value="one_to_three_days">1–3 days</option>
                <option value="four_to_seven_days">4–7 days</option>
                <option value="more_than_one_week">More than a week</option>
              </select>
            </label>
            <label className="field-label" htmlFor="symptom-severity">How would you describe the severity?
              <select id="symptom-severity" value={severity} onChange={(event) => { setSeverity(event.target.value as Severity); setResult(null); setReviewStatuses({}); }}>
                <option value="not_sure">Not sure</option>
                <option value="mild">Mild</option>
                <option value="moderate">Moderate</option>
                <option value="severe">Severe</option>
              </select>
            </label>
            <label className="field-label" htmlFor="symptom-onset">How did they begin?
              <select id="symptom-onset" value={onset} onChange={(event) => { setOnset(event.target.value as Onset); setResult(null); setReviewStatuses({}); }}>
                <option value="not_sure">Not sure</option>
                <option value="sudden">Suddenly</option>
                <option value="gradual">Gradually</option>
                <option value="comes_and_goes">They come and go</option>
              </select>
            </label>
          </div>
        </fieldset>

        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="button button-primary symptom-submit" disabled={loading || !text.trim()} type="submit">
          {loading ? "Reviewing information..." : "Review symptom information"} <span aria-hidden="true">→</span>
        </button>
      </form>

      {result && (
        <section className="symptom-result" aria-live="polite">
          <div className="symptom-result-heading">
            <div><div className="eyebrow">TEXT REVIEW COMPLETE</div><h2>Recognized phrases</h2></div>
            <span className="review-pill">Human review required</span>
          </div>
          {reviewItems.length > 0 ? (
            <div className="symptom-human-review">
              <div className="human-review-intro">
                <h3>Confirm what you meant</h3>
                <p>Phrase matching can misunderstand context. For each item, choose the option that best reflects your experience. Nothing is assumed to be present until you review it.</p>
              </div>
              {reviewItems.map((item) => {
                const contextFlag = "context_flag" in item ? item.context_flag : null;
                return (
                  <div className="human-review-item" key={item.id}>
                    <div className="human-review-term">
                      <strong>{item.label}</strong>
                      <small>{contextFlag ? (contextLabels[String(contextFlag)] ?? "Context needs review") : item.category}</small>
                    </div>
                    <label className="field-label" htmlFor={`review-${item.id}`}>
                      Your confirmation
                      <select
                        id={`review-${item.id}`}
                        value={reviewStatuses[item.id] ?? "unsure"}
                        onChange={(event) => setReviewStatuses((current) => ({
                          ...current,
                          [item.id]: event.target.value as ReviewStatus,
                        }))}
                      >
                        <option value="unsure">Not sure / needs review</option>
                        <option value="present">I am experiencing this</option>
                        <option value="not_present">I am not experiencing this</option>
                      </select>
                    </label>
                  </div>
                );
              })}
              <div className="human-review-counts" aria-live="polite">
                <span>{reviewCounts.present} confirmed by you</span>
                <span>{reviewCounts.not_present} marked absent</span>
                <span>{reviewCounts.unsure} still unsure</span>
              </div>
              <p className="human-review-note">These are your own confirmations for this page only. They are not saved, sent as a diagnosis, or interpreted by a medical model.</p>
            </div>
          ) : (
            <p className="symptom-empty">No supported symptom phrases were confidently recognized from this limited vocabulary. This does not mean that no symptoms are present. Please review your original description with a healthcare professional if you are concerned.</p>
          )}

          <div className="reported-context-summary">
            <h3>Your reported context</h3>
            <p>Duration: <strong>{result.reported_context.duration.replaceAll("_", " ")}</strong></p>
            <p>Severity: <strong>{result.reported_context.severity.replaceAll("_", " ")}</strong></p>
            <p>Onset: <strong>{result.reported_context.onset.replaceAll("_", " ")}</strong></p>
            <small>These are self-reported details. The system has not interpreted or verified them.</small>
          </div>

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
