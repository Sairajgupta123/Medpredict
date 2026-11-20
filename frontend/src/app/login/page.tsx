import type { Metadata } from "next";
import Link from "next/link";
import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main id="main-content" className="auth-page">
      <div className="auth-side">
        <Link className="back-link" href="/">← Back to MediPredict</Link>
        <div className="auth-side-copy">
          <div className="eyebrow eyebrow-light">A MORE THOUGHTFUL HEALTH EXPERIENCE</div>
          <h2>Clarity begins with <em>good information.</em></h2>
          <p>Access your project workspace with a secure account. MediPredict remains an academic prototype, not a diagnostic service.</p>
        </div>
        <span className="auth-side-foot">MEDIPREDICT · HEALTH, WITH CLARITY</span>
      </div>
      <div className="auth-main"><AuthForm mode="login" /></div>
    </main>
  );
}
