"use client";

import { useState, type FormEvent } from "react";

export function AccountDeletionForm() {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/auth/me/deletion-request", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ password }),
        cache: "no-store",
      });
      const result = await response.json().catch(() => null) as
        | { message?: string; detail?: string }
        | null;
      if (!response.ok) {
        setError(result?.detail || "The deletion request could not be submitted.");
        return;
      }
      setPassword("");
      setMessage(result?.message || "Your account has been disabled and deletion is queued.");
      window.location.assign("/");
    } catch {
      setError("The MediPredict server is unavailable. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="account-deletion-panel" aria-labelledby="account-deletion-title">
      <div>
        <span className="eyebrow">ACCOUNT PRIVACY</span>
        <h2 id="account-deletion-title">Delete your account</h2>
        <p>
          Your account will be disabled immediately. Personal prediction records and
          private images are queued for removal. Some minimal audit records may be retained.
          If private image storage is unavailable, erasure remains pending until it can be retried.
        </p>
      </div>
      <form onSubmit={submit}>
        <label htmlFor="account-deletion-password">Confirm with your current password</label>
        <input
          id="account-deletion-password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !password}>
          {busy ? "Submitting request..." : "Request account deletion"}
        </button>
      </form>
      {error ? <p className="account-deletion-error" role="alert">{error}</p> : null}
      {message ? <p role="status">{message}</p> : null}
    </section>
  );
}
