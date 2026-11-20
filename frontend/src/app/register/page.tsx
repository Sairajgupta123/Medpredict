import type { Metadata } from "next";
import Link from "next/link";
import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <main id="main-content" className="auth-page">
      <div className="auth-side">
        <Link className="back-link" href="/">← Back to MediPredict</Link>
        <div className="auth-side-copy">
          <div className="eyebrow eyebrow-light">YOUR WORKSPACE STARTS HERE</div>
          <h2>Built on trust. <em>Designed for clarity.</em></h2>
          <p>Create an account to explore the evolving MediPredict workspace and its research modules.</p>
        </div>
        <span className="auth-side-foot">MEDIPREDICT · HEALTH, WITH CLARITY</span>
      </div>
      <div className="auth-main"><AuthForm mode="register" /></div>
    </main>
  );
}
