"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

type AuthMode = "login" | "register";

type AuthFormProps = {
  mode: AuthMode;
};

type AuthResult = {
  user?: { display_name?: string | null; email?: string };
  detail?: string;
};

export function AuthForm({ mode }: AuthFormProps) {
  const isRegister = mode === "register";
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          password,
          ...(isRegister ? { display_name: displayName.trim() || null } : {}),
        }),
        signal: AbortSignal.timeout(15_000),
      });
      const result = await response.json().catch(() => null) as AuthResult | null;
      if (!response.ok) {
        setError(result?.detail ?? "We could not complete your request. Please try again.");
        return;
      }
      window.location.assign("/dashboard");
    } catch {
      setError("Unable to reach MediPredict. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="auth-card" aria-labelledby="auth-title">
      <div className="auth-card-brand"><span className="brand-mark" aria-hidden="true"><span /><span /></span><span>MediPredict</span></div>
      <div className="eyebrow"><span className="eyebrow-dot" /> YOUR PRIVATE WORKSPACE</div>
      <h1 id="auth-title">{isRegister ? "Create your account." : "Welcome back."}</h1>
      <p className="auth-intro">{isRegister ? "Set up an account to access your MediPredict project workspace." : "Sign in to continue to your MediPredict workspace."}</p>

      <form className="auth-form" onSubmit={handleSubmit}>
        {isRegister && (
          <label className="field-label">
            Name <span>Optional</span>
            <input
              autoComplete="name"
              maxLength={120}
              name="display_name"
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Your name"
              value={displayName}
            />
          </label>
        )}
        <label className="field-label">
          Email address
          <input
            autoComplete="email"
            maxLength={320}
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            required
            type="email"
            value={email}
          />
        </label>
        <label className="field-label">
          Password
          <input
            autoComplete={isRegister ? "new-password" : "current-password"}
            maxLength={128}
            minLength={isRegister ? 8 : 1}
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            placeholder={isRegister ? "At least 8 characters" : "Enter your password"}
            required
            type="password"
            value={password}
          />
        </label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="button button-primary auth-submit" disabled={submitting} type="submit">
          {submitting ? "Please wait..." : isRegister ? "Create account" : "Sign in"}
          <span aria-hidden="true">→</span>
        </button>
      </form>
      <p className="auth-switch">
        {isRegister ? "Already have an account?" : "New to MediPredict?"}{" "}
        <Link href={isRegister ? "/login" : "/register"}>{isRegister ? "Sign in" : "Create an account"}</Link>
      </p>
      <p className="auth-privacy">Your password is sent over your connection to the MediPredict API and is never stored in browser storage. Use a unique password.</p>
    </section>
  );
}
