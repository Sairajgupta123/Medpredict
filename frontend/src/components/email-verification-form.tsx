"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

type Props = { initialToken?: string };

export function EmailVerificationForm({ initialToken = "" }: Props) {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState(initialToken);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function requestLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch("/api/auth/email-verification/request", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ email: email.trim() }),
        signal: AbortSignal.timeout(12_000),
      });
      const result = await response.json().catch(() => null) as { message?: string; detail?: string } | null;
      if (!response.ok) {
        setError(result?.detail ?? "We could not send the verification request.");
      } else {
        setMessage(result?.message ?? "If the account needs verification, instructions will be sent.");
      }
    } catch {
      setError("Unable to reach MediPredict. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch("/api/auth/email-verification/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ token: token.trim() }),
        signal: AbortSignal.timeout(12_000),
      });
      const result = await response.json().catch(() => null) as { message?: string; detail?: string } | null;
      if (!response.ok) {
        setError(result?.detail ?? "This verification link is invalid or expired.");
      } else {
        setMessage(result?.message ?? "Your email address has been verified.");
        setToken("");
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
          <div className="eyebrow eyebrow-light">ACCOUNT SECURITY</div>
          <h2>One more step. <em>Verify your email.</em></h2>
          <p>Confirm that you control the email address linked to your MediPredict account.</p>
        </div>
        <span className="auth-side-foot">MEDIPREDICT · HEALTH, WITH CLARITY</span>
      </div>
      <div className="auth-main">
        <section className="auth-card" aria-labelledby="verify-title">
          <div className="auth-card-brand"><span className="brand-mark" aria-hidden="true"><span /><span /></span><span>MediPredict</span></div>
          <div className="eyebrow"><span className="eyebrow-dot" /> EMAIL VERIFICATION</div>
          <h1 id="verify-title">Verify your account.</h1>
          <p className="auth-intro">Use the link from your email, or request a fresh verification message.</p>
          <form className="auth-form" onSubmit={verify}>
            <label className="field-label">
              Verification token
              <input
                autoComplete="off"
                maxLength={256}
                onChange={(event) => setToken(event.target.value)}
                placeholder="Paste the token from your email"
                required
                value={token}
              />
            </label>
            <button className="button button-primary auth-submit" disabled={busy || token.trim().length < 32} type="submit">
              {busy ? "Please wait..." : "Verify email"} <span aria-hidden="true">→</span>
            </button>
          </form>
          <div className="auth-form" aria-label="Request another verification email">
            <label className="field-label">
              Email address
              <input
                autoComplete="email"
                maxLength={320}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                type="email"
                value={email}
              />
            </label>
            <button className="button button-secondary auth-submit" disabled={busy || !email.trim()} onClick={() => {
              const form = document.getElementById("verification-request-form") as HTMLFormElement | null;
              form?.requestSubmit();
            }} type="button">
              Send verification link
            </button>
            <form id="verification-request-form" onSubmit={requestLink} />
          </div>
          {message && <p className="auth-success" role="status">{message}</p>}
          {error && <p className="auth-error" role="alert">{error}</p>}
          <p className="auth-switch"><Link href="/login">Return to sign in</Link></p>
          <p className="auth-privacy">Verification links expire after 30 minutes and can be used once.</p>
        </section>
      </div>
    </main>
  );
}
