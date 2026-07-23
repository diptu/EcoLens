/**
 * /verify-email — Email verification pending screen.
 * Two-panel layout: paper plane + tagline on the left, resend card on the right.
 */
import { MailCheck, RotateCw } from "lucide-react";

import {
  AuthLayout,
  AuthButton,
  AuthHeader,
  AuthDivider,
} from "@/components/auth/auth-layout";

export const metadata = {
  title: "Verify your email — EcoLens",
  description: "Confirm your email to activate your EcoLens account.",
};

export default function VerifyEmailPage() {
  return (
    <AuthLayout
      illustration="plane"
      tagline={<>One step closer to making an impact.</>}
      subTagline="Verify your email to unlock the full EcoLens platform and start measuring your carbon footprint."
    >
      <AuthHeader
        title="Verify Your Email"
        breadcrumb={{ label: "/verify-email", href: "/verify-email" }}
      />

      <div className="mb-5 flex flex-col items-center text-center">
        <span className="grid h-14 w-14 place-items-center rounded-full bg-emerald-400/10 text-emerald-300">
          <MailCheck className="h-7 w-7" />
        </span>
        <p className="mt-4 text-sm text-white/70">
          We&apos;ve sent a verification link to
        </p>
        <p className="mt-1 text-sm font-semibold text-white">
          diptu.alam@company.com
        </p>
        <p className="mt-3 max-w-sm text-xs text-white/50">
          Please check your inbox and click on the link to verify your email address.
        </p>
      </div>

      <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
        <p className="text-sm font-semibold text-white">Haven&apos;t received the email?</p>
        <p className="mt-1 text-xs text-white/55">
          Check your spam folder or resend the email.
        </p>
        <AuthButton type="button" className="mt-3">
          <RotateCw className="h-3.5 w-3.5" /> Resend Email
        </AuthButton>
      </div>

      <div className="mt-5">
        <AuthDivider label="or" />
        <a
          href="/login"
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-xs font-medium text-white/80 hover:bg-white/[0.07] hover:text-white"
        >
          ← Back to Login
        </a>
      </div>
    </AuthLayout>
  );
}
