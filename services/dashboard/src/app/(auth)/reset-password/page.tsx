/**
 * /reset-password — Set a new password (with strength checklist).
 * Two-panel layout: shield + tagline on the left, password form on the right.
 */
import { Eye, Check } from "lucide-react";

import {
  AuthLayout,
  AuthField,
  AuthButton,
  AuthHeader,
  AuthDivider,
} from "@/components/auth/auth-layout";

const STEPS = [
  { id: 1, label: "Verify" },
  { id: 2, label: "New Password" },
  { id: 3, label: "Confirm" },
] as const;

const REQUIREMENTS = [
  "At least 8 characters",
  "One uppercase letter",
  "One number",
  "One special character",
];

export const metadata = {
  title: "Reset password — EcoLens",
  description: "Set a new password for your EcoLens account.",
};

export default function ResetPasswordPage() {
  return (
    <AuthLayout
      illustration="shield"
      tagline={<>Stronger security for a sustainable future.</>}
      subTagline="Your data is encrypted end-to-end. Choose a strong password to keep it that way."
    >
      <AuthHeader
        title="Reset Password"
        breadcrumb={{ label: "/reset-password", href: "/reset-password" }}
      />

      {/* Step indicator */}
      <ol className="mb-6 flex items-center">
        {STEPS.map((s, i) => (
          <li key={s.id} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1.5">
              <span
                className={
                  s.id <= 2
                    ? "grid h-7 w-7 place-items-center rounded-full bg-emerald-400 text-xs font-bold text-black ring-2 ring-emerald-400/30"
                    : "grid h-7 w-7 place-items-center rounded-full border border-white/20 bg-white/5 text-xs font-bold text-white/40"
                }
              >
                {s.id < 2 ? <Check className="h-3.5 w-3.5" /> : s.id}
              </span>
              <span className={s.id <= 2 ? "text-[10px] font-medium text-white" : "text-[10px] text-white/40"}>
                {s.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <span className="mx-1 mb-5 h-0.5 flex-1 bg-emerald-400/40" />
            )}
          </li>
        ))}
      </ol>

      <p className="mb-4 text-sm text-white/60">
        Create a new password for your account.
      </p>

      <form className="space-y-4">
        <AuthField
          label="New password"
          name="password"
          type="password"
          placeholder="Enter new password"
          autoComplete="new-password"
          icon={<Eye className="h-4 w-4" />}
        />
        <ul className="space-y-1.5 pl-1">
          {REQUIREMENTS.map((r) => (
            <li key={r} className="flex items-center gap-2 text-[11px] text-white/60">
              <Check className="h-3 w-3 text-emerald-300" />
              {r}
            </li>
          ))}
        </ul>
        <AuthField
          label="Confirm new password"
          name="confirm"
          type="password"
          placeholder="Confirm new password"
          autoComplete="new-password"
          icon={<Eye className="h-4 w-4" />}
        />
        <AuthButton type="submit" className="mt-2">Reset Password</AuthButton>
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
    </AuthLayout>
  );
}
