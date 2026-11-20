import type { Metadata } from "next";
import Link from "next/link";
import { SymptomChecker } from "@/components/symptom-checker";

export const metadata: Metadata = {
  title: "Symptom phrase review",
  description: "A limited, non-diagnostic symptom phrase recognition research prototype.",
};

export default function SymptomCheckerPage() {
  return (
    <main id="main-content" className="symptom-page">
      <div className="container symptom-container">
        <Link className="back-link" href="/dashboard">← Back to workspace</Link>
        <SymptomChecker />
      </div>
    </main>
  );
}
