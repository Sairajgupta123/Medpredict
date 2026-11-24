import type { Metadata } from "next";
import { EmailVerificationForm } from "@/components/email-verification-form";

export const metadata: Metadata = { title: "Verify email" };

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const params = await searchParams;
  return <EmailVerificationForm initialToken={params.token ?? ""} />;
}
