import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getSessionUser } from "@/lib/auth-proxy";
import { SkinImageIntake } from "@/components/skin-image-intake";

export const metadata: Metadata = {
  title: "Private skin image intake",
  description: "Consent-first private skin image intake for the MediPredict research prototype.",
};

export default async function SkinImagePage() {
  const session = await getSessionUser();
  if (!session.user) redirect("/login");

  return (
    <main id="main-content" className="symptom-page skin-intake-page">
      <div className="container symptom-container">
        <Link className="back-link" href="/dashboard">← Back to workspace</Link>
        <SkinImageIntake />
      </div>
    </main>
  );
}
