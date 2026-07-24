"use client";

/** ECO-131: interactive signup form (see login-form.tsx for the pattern/rationale). */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Eye } from "lucide-react";

import { AuthField, AuthButton, AuthDivider, SocialAuthButton } from "@/components/auth/auth-layout";
import { useAuth } from "@/lib/auth";

export function SignupForm() {
  const router = useRouter();
  const { signup } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const form = new FormData(e.currentTarget);
    const fullName = String(form.get("fullName") ?? "");
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm") ?? "");
    const agreed = form.get("agree") === "on";

    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    if (!agreed) {
      setError("You must agree to the Terms of Service and Privacy Policy.");
      return;
    }

    setSubmitting(true);
    const result = await signup(fullName, email, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    router.push("/onboarding");
  }

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <AuthField label="Full name" name="fullName" placeholder="Enter your full name" autoComplete="name" />
      <AuthField label="Work email" name="email" type="email" placeholder="Enter your work email" autoComplete="email" />
      <AuthField label="Company name" name="company" placeholder="Enter your company name" autoComplete="organization" />
      <AuthField
        label="Password"
        name="password"
        type="password"
        placeholder="Create a password"
        autoComplete="new-password"
        icon={<Eye className="h-4 w-4" />}
      />
      <AuthField
        label="Confirm password"
        name="confirm"
        type="password"
        placeholder="Confirm your password"
        autoComplete="new-password"
        icon={<Eye className="h-4 w-4" />}
      />

      {error && (
        <p role="alert" className="rounded-md border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      )}

      <label className="flex items-start gap-2 pt-1 text-xs text-white/60">
        <input
          type="checkbox"
          name="agree"
          className="mt-0.5 h-3.5 w-3.5 rounded border-white/20 bg-white/5 text-emerald-400 focus:ring-emerald-400/30"
        />
        <span>
          I agree to the{" "}
          <a className="text-emerald-300 hover:text-emerald-200" href="#">
            Terms of Service
          </a>{" "}
          and{" "}
          <a className="text-emerald-300 hover:text-emerald-200" href="#">
            Privacy Policy
          </a>
          .
        </span>
      </label>

      <AuthButton type="submit" className="mt-2" disabled={submitting}>
        {submitting ? "Creating account…" : "Create Account"}
      </AuthButton>

      <div className="mt-5">
        <AuthDivider label="or sign up with" />
        <div className="mt-3 flex gap-3">
          <SocialAuthButton provider="Google" />
          <SocialAuthButton provider="Microsoft" />
        </div>
      </div>
    </form>
  );
}
