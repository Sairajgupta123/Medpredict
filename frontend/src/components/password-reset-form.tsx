"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

type ApiResult = { message?: string; detail?: string };

export function PasswordResetForm() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const fragment = window.location.hash;
    if (!fragment) return;
    const candidate = new URLSearchParams(fragment.slice(1)).get("token");
    if (candidate) setToken(candidate);
    // Remove the one-time token from the visible URL and browser history.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }, []);

  async function requestReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/auth/password-reset/request", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ email: email.trim() }),
        cache: "no-store",
        signal: AbortSignal.timeout(12_000),
      });
      const result = await response.json().catch(() => null) as ApiResult | null;
      if (!response.ok) {
        setError(result?.detail ?? "We could not process the reset request.");
      } else {
        setMessage(result?.message ?? "If an account exists for this email, password reset instructions will be sent.");
      }
    } catch {
      setError("Unable to reach MediPredict. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    if (password !== confirmation) {
      setError("The passwords do not match.");
      setBusy(false);
      return;
    }
    try {
      const response = await fetch("/api/auth/password-reset/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ token: token.trim(), new_password: password }),
        cache: "no-store",
        signal: AbortSignal.timeout(12_000),
      });
      const result = await response.json().catch(() => null) as ApiResult | null;
      if (!response.ok) {
        setError(result?.detail ?? "This reset link is invalid or expired.");
      } else {
        setMessage(result?.message ?? "Your password has been reset. You can now sign in.");
        setToken("");
        setPassword("");
        setConfirmation("");
      }
    } catch {
      setError("Unable to reach MediPredict. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main-content" className="auth-page">
      <div className="auth-side">
        <Link className="back-link" href="/">← Back to MediPredict</Link>
        <div className="auth-side-copy">
          <div className="eyebrow eyebrow-light">ACCOUNT RECOVERY</div>
          <h2>Back to your <em>workspace.</em></h2>
          <p>Request a secure, time-limited link or set a new password using the link sent to your email.</p>
        </div>
        <span className="auth-side-foot">MEDIPREDICT · HEALTH, WITH CLARITY</span>
      </div>
      <div className="auth-main">
        <section className="auth-card" aria-labelledby="reset-title">
          <div className="auth-card-brand"><span className="brand-mark" aria-hidden="true"><span /><span /></span><span>MediPredict</span></div>
          <div className="eyebrow"><span className="eyebrow-dot" /> PASSWORD RECOVERY</div>
          <h1 id="reset-title">Reset your password.</h1>
          <p className="auth-intro">Reset links expire after 30 minutes and can be used once.</p>
          {token ? (
            <form className="auth-form" onSubmit={confirmReset}>
              <label className="field-label">
                New password
                <input autoComplete="new-password" minLength={8} maxLength={128} required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
              </label>
              <label className="field-label">
                Confirm new password
                <input autoComplete="new-password" minLength={8} maxLength={128} required type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
              </label>
              <button className="button button-primary auth-submit" disabled={busy || token.length < 32} type="submit">
                {busy ? "Please wait..." : "Set new password"} <span aria-hidden="true">→</span>
              </button>
            </form>
          ) : (
            <form className="auth-form" onSubmit={requestReset}>
              <label className="field-label">
                Email address
                <input autoComplete="email" maxLength={320} required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
              </label>
              <button className="button button-primary auth-submit" disabled={busy || !email.trim()} type="submit">
                {busy ? "Please wait..." : "Send reset link"} <span aria-hidden="true">→</span>
              </button>
            </form>
          )}
          {message && <p className="auth-success" role="status">{message}</p>}
          {error && <p className="auth-error" role="alert">{error}</p>}
          <p className="auth-switch"><Link href="/login">Return to sign in</Link></p>
        </section>
      </div>
    </main>
  );
}
