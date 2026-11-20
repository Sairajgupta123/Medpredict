"use client";

import { useCallback, useEffect, useState } from "react";

type ReviewItem = {
  target_type: "disease" | "symptom" | "disease_symptom";
  target_key: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string | null;
};

const statusOptions = [
  { value: "in_review", label: "Move to in review" },
  { value: "approved", label: "Approve for publication" },
  { value: "retired", label: "Retire entry" },
  { value: "draft", label: "Return to draft" },
];

const typeLabels: Record<ReviewItem["target_type"], string> = {
  disease: "Disease",
  symptom: "Symptom",
  disease_symptom: "Disease–symptom link",
};

export function CatalogReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [filters, setFilters] = useState({ targetType: "all", status: "draft" });

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ limit: "100", status: filters.status });
    if (filters.targetType !== "all") params.set("target_type", filters.targetType);

    try {
      const response = await fetch(`/api/catalog/review?${params.toString()}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result?.detail ?? "Could not load the review queue.");
      }
      setItems(Array.isArray(result) ? result : []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load the review queue.");
    } finally {
      setLoading(false);
    }
  }, [filters.status, filters.targetType]);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  async function submitDecision(
    item: ReviewItem,
    form: HTMLFormElement,
  ) {
    const formData = new FormData(form);
    const status = String(formData.get("status") ?? "");
    const reason = String(formData.get("reason") ?? "").trim();
    if (reason.length < 8) {
      setError("Please provide a review reason with at least 8 characters.");
      return;
    }

    const key = `${item.target_type}:${item.target_key}`;
    setBusyKey(key);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/catalog/review", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          target_type: item.target_type,
          target_key: item.target_key,
          status,
          reason,
        }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result?.detail ?? "The review decision could not be saved.");
      }
      setNotice(`Saved review decision for “${item.name}”.`);
      await loadQueue();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The review decision could not be saved.");
    } finally {
      setBusyKey("");
    }
  }

  return (
    <section className="review-workspace" aria-labelledby="review-queue-title">
      <div className="review-toolbar">
        <div>
          <span className="eyebrow">REVIEW OPERATIONS</span>
          <h2 id="review-queue-title">Catalog review queue</h2>
          <p>Review each catalog entry and record the evidence or rationale behind your decision.</p>
        </div>
        <div className="review-filters">
          <label>
            <span>Entry type</span>
            <select
              value={filters.targetType}
              onChange={(event) => setFilters((current) => ({ ...current, targetType: event.target.value }))}
            >
              <option value="all">All types</option>
              <option value="disease">Diseases</option>
              <option value="symptom">Symptoms</option>
              <option value="disease_symptom">Disease–symptom links</option>
            </select>
          </label>
          <label>
            <span>Status</span>
            <select
              value={filters.status}
              onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
            >
              <option value="draft">Draft</option>
              <option value="in_review">In review</option>
              <option value="approved">Approved</option>
              <option value="retired">Retired</option>
            </select>
          </label>
          <button className="review-refresh" type="button" onClick={() => void loadQueue()}>
            Refresh
          </button>
        </div>
      </div>

      {notice && <p className="review-message review-message-success" role="status">{notice}</p>}
      {error && <p className="review-message review-message-error" role="alert">{error}</p>}
      {loading ? (
        <div className="review-empty" role="status">Loading review queue…</div>
      ) : items.length === 0 ? (
        <div className="review-empty">
          <strong>No entries match these filters.</strong>
          <span>Try another status or entry type. New catalog entries will appear here when submitted for review.</span>
        </div>
      ) : (
        <div className="review-list">
          {items.map((item) => {
            const key = `${item.target_type}:${item.target_key}`;
            return (
              <article className="review-item" key={key}>
                <div className="review-item-heading">
                  <div>
                    <span className="review-item-type">{typeLabels[item.target_type]}</span>
                    <h3>{item.name}</h3>
                    <code>{item.target_key}</code>
                  </div>
                  <span className={`review-status review-status-${item.status}`}>{item.status.replace("_", " ")}</span>
                </div>
                {item.description && <p className="review-item-description">{item.description}</p>}
                <form
                  className="review-decision-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submitDecision(item, event.currentTarget);
                  }}
                >
                  <label>
                    <span>Decision</span>
                    <select name="status" defaultValue="in_review">
                      {statusOptions.map((option) => (
                        <option value={option.value} key={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="review-reason-field">
                    <span>Review reason <small>(required, 8–1,000 characters)</small></span>
                    <textarea name="reason" minLength={8} maxLength={1000} required rows={2} placeholder="Record what was checked and why this decision is appropriate." />
                  </label>
                  <button className="review-submit" type="submit" disabled={busyKey === key}>
                    {busyKey === key ? "Saving…" : "Save decision"}
                  </button>
                </form>
              </article>
            );
          })}
        </div>
      )}
      <p className="review-safety-note">
        Approval makes an entry eligible for public catalog display; it does not establish clinical validity.
        Review only within your verified role and assigned scope.
      </p>
    </section>
  );
}
