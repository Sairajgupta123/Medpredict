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
  model_inference_performed: false;
  disease_prediction_performed: false;
  research_only: true;
  disclaimer: string;
};
type SymptomCatalog = {
  taxonomy_version: string;
  status: string;
  symptoms: SymptomItem[];
  disclaimer: string;
};

type CatalogMatchItem = {
  disease_code: string;
  disease_name: string;
  catalog_symptom_count: number;
  matched_symptoms: { symptom_code: string; symptom_name: string }[];
  matched_symptom_count: number;
  catalog_overlap_ratio: number;
};
type CatalogMatchResult = {
  method: "approved_catalog_overlap";
  results: CatalogMatchItem[];
  disclaimer: string;
  clinical_interpretation_performed: false;
  disease_probability_provided: false;
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
  const [matchResult, setMatchResult] = useState<CatalogMatchResult | null>(null);
  const [matchError, setMatchError] = useState("");
  const [matchLoading, setMatchLoading] = useState(false);

  useEffect(() => {
    let active = true;
    fetch("/api/symptoms/catalog", { headers: { Accept: "application/json" }, cache: "no-store", signal: AbortSignal.timeout(6_000) })
      .then(async (response) => {
        const body = await response.json() as SymptomCatalog & { detail?: string };
        if (!response.ok) throw new Error(body.detail ?? "Could not load the symptom list.");
        if (
          typeof body.taxonomy_version !== "string" ||
          typeof body.status !== "string" ||
          typeof body.disclaimer !== "string" ||
          !Array.isArray(body.symptoms) ||
          !body.symptoms.every((item) =>
            item && typeof item.id === "string" && /^[A-Z0-9_]{2,80}$/.test(item.id) &&
            typeof item.label === "string" && item.label.trim().length > 0 && item.label.length <= 120 &&
            typeof item.category === "string" && item.category.trim().length > 0 && item.category.length <= 80
          ) ||
          new Set(body.symptoms.map((item) => item.id)).size !== body.symptoms.length
        ) throw new Error("The symptom list returned an unexpected response.");
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

  async function handleCatalogMatch() {
    const symptomIds = reviewItems
      .filter((item) => reviewStatuses[item.id] === "present")
      .map((item) => item.id);
    if (symptomIds.length === 0) {
      setMatchError("Confirm at least one symptom as present before comparing the catalog.");
      return;
    }
    setMatchError("");
    setMatchResult(null);
    setMatchLoading(true);
    try {
      const response = await fetch("/api/symptoms/catalog-match", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ symptom_ids: symptomIds }),
        cache: "no-store",
        signal: AbortSignal.timeout(12_000),
      });
      const body = await response.json() as CatalogMatchResult & { detail?: string };
      if (!response.ok) {
        setMatchError(body.detail ?? "The approved catalog could not be compared.");
        return;
      }
      if (
        body.method !== "approved_catalog_overlap" ||
        body.clinical_interpretation_performed !== false ||
        body.disease_probability_provided !== false ||
        typeof body.disclaimer !== "string" || body.disclaimer.trim().length === 0 ||
        !Array.isArray(body.results) ||
        !body.results.every((item) => item &&
          typeof item.disease_code === "string" && item.disease_code.trim().length > 0 &&
          typeof item.disease_name === "string" && item.disease_name.trim().length > 0 &&
          Number.isInteger(item.catalog_symptom_count) && item.catalog_symptom_count > 0 &&
          Number.isInteger(item.matched_symptom_count) && item.matched_symptom_count > 0 &&
          item.matched_symptom_count <= item.catalog_symptom_count &&
          Array.isArray(item.matched_symptoms) && item.matched_symptoms.length === item.matched_symptom_count &&
          item.matched_symptoms.every((symptom) => symptom &&
            typeof symptom.symptom_code === "string" && symptom.symptom_code.trim().length > 0 &&
            typeof symptom.symptom_name === "string" && symptom.symptom_name.trim().length > 0) &&
          typeof item.catalog_overlap_ratio === "number" && Number.isFinite(item.catalog_overlap_ratio) &&
          item.catalog_overlap_ratio >= 0 && item.catalog_overlap_ratio <= 1)
      ) {
        setMatchError("The catalog service returned an unexpected response. No result was displayed.");
        return;
      }
      setMatchResult(body);
    } catch {
      setMatchError("Unable to connect to the catalog service. Please try again later.");
    } finally {
      setMatchLoading(false);
    }
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
        signal: AbortSignal.timeout(15_000),
      });
      const body = await response.json() as NormalizeResult & { detail?: string };
      if (!response.ok) {
        setError(body.detail ?? "We could not process this information. Please try again.");
        return;
      }
      if (
        typeof body.taxonomy_version !== "string" || body.taxonomy_version.trim().length === 0 ||
        typeof body.unrecognized_text_present !== "boolean" || body.review_required !== true ||
        typeof body.reason !== "string" || body.reason.trim().length === 0 ||
        typeof body.disclaimer !== "string" || body.disclaimer.trim().length === 0 ||
        !body.reported_context || body.reported_context.duration !== duration ||
        body.reported_context.severity !== severity || body.reported_context.onset !== onset ||
        !Array.isArray(body.matched_symptoms) || !Array.isArray(body.contextual_mentions) ||
        ![...body.matched_symptoms, ...body.contextual_mentions].every((item) => item &&
          typeof item.id === "string" && /^[A-Z0-9_]{2,80}$/.test(item.id) &&
          typeof item.label === "string" && item.label.trim().length > 0 && item.label.length <= 120 &&
          typeof item.category === "string" && item.category.trim().length > 0 && item.category.length <= 80) ||
        new Set([...body.matched_symptoms, ...body.contextual_mentions].map((item) => item.id)).size !==
          body.matched_symptoms.length + body.contextual_mentions.length ||
        !body.contextual_mentions.every((item) =>
          ["negated_or_denied_context", "possibly_historical_context", "uncertain_context", "explicit_mention_unresolved"].includes(item.context_flag)) ||
        body.clinical_interpretation_performed !== false || body.model_inference_performed !== false ||
        body.disease_prediction_performed !== false || body.research_only !== true
      ) {
        setError("The symptom service returned an unexpected response. No result was displayed.");
        return;
      }
      setResult(body);
      setMatchResult(null);
      setMatchError("");
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

  const confirmedSymptomCount = reviewItems.filter((item) => reviewStatuses[item.id] === "present").length;

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
                        onChange={(event) => {
                          setReviewStatuses((current) => ({
                            ...current,
                            [item.id]: event.target.value as ReviewStatus,
                          }));
                          // A changed confirmation invalidates any previous catalog comparison.
                          setMatchResult(null);
                          setMatchError("");
                        }}
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

          {reviewItems.length > 0 && (
            <section className="catalog-match-panel" aria-labelledby="catalog-match-title">
              <div className="human-review-intro">
                <h3 id="catalog-match-title">Compare with the approved catalog</h3>
                <p>Only symptoms you explicitly confirm as present are sent. This compares catalog associations; it does not estimate disease risk or provide a diagnosis.</p>
              </div>
              <button
                className="button button-secondary"
                disabled={matchLoading || confirmedSymptomCount === 0}
                onClick={handleCatalogMatch}
                type="button"
              >
                {matchLoading ? "Comparing approved entries..." : `Compare ${confirmedSymptomCount} confirmed symptom(s)`}
              </button>
              {matchError && <p className="auth-error" role="alert">{matchError}</p>}
              {matchResult && (
                <div className="catalog-match-results" aria-live="polite">
                  {matchResult.results.length > 0 ? (
                    <ul>
                      {matchResult.results.map((item) => (
                        <li key={item.disease_code}>
                          <strong>{item.disease_name}</strong>
                          <span>{item.matched_symptom_count} of {item.catalog_symptom_count} approved catalog associations matched</span>
                          <small>Catalog overlap: {(item.catalog_overlap_ratio * 100).toFixed(0)}% — not a probability or risk score</small>
                          <small>Matched terms: {item.matched_symptoms.map((symptom) => symptom.symptom_name).join(", ")}</small>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>No approved disease associations matched these confirmed symptoms. This does not rule out any condition.</p>
                  )}
                  <p className="human-review-note">{matchResult.disclaimer}</p>
                </div>
              )}
            </section>
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
