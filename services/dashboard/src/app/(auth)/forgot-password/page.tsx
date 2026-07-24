/**
 * /forgot-password — Request a password reset link.
 * Two-panel layout: sapling + tagline on the left, email form on the right.
 */
import { Inbox } from "lucide-react";

import {
  AuthLayout,
  AuthField,
  AuthButton,
  AuthHeader,
  AuthFooter,
  AuthDivider,
} from "@/components/auth/auth-layout";

export const metadata = {
  title: "Forgot password — EcoLens",
  description: "Reset your EcoLens account password.",
};

export default function ForgotPasswordPage() {
  return (
    <AuthLayout
      illustration="sapling"
      tagline={<>Sustainability starts with action.</>}
      subTagline="We make it easy to get back to your dashboard and keep your data moving."
    >
      <AuthHeader
        title="Forgot Password"
        breadcrumb={{ label: "/forgot-password", href: "/forgot-password" }}
      />

      <div className="mb-5 flex justify-center">
        <span className="grid h-14 w-14 place-items-center rounded-full bg-emerald-400/10 text-emerald-300">
          <Inbox className="h-7 w-7" />
        </span>
      </div>
      <p className="mb-5 text-center text-sm text-white/70">
        No worries! Enter your work email and we&apos;ll send you a link to reset your password.
      </p>

      <form className="space-y-4">
        <AuthField
          label="Work email"
          name="email"
          type="email"
          placeholder="Enter your work email"
          autoComplete="email"
        />
        <AuthButton type="submit">Send Reset Link</AuthButton>
      </form>

      <div className="mt-5">
        <AuthDivider label="or" />
        <a
          href="/login"
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-xs font-medium text-white/80 hover:bg-white/[0.07] hover:text-white"
        >
          ← Back to Login
        </a>
      </div>

      <AuthFooter
        text="Need help?"
        linkLabel="Contact support"
        linkHref="mailto:support@ecolens.app"
      />
    </AuthLayout>
  );
}
