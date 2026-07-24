"use client";

/**
 * ECO-131: the actual interactive login form. Split out from
 * `app/(auth)/login/page.tsx` because that file exports `metadata`,
 * which requires a Server Component -- this client child owns all the
 * state/handlers instead.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Eye } from "lucide-react";

import { AuthField, AuthButton, AuthDivider, SocialAuthButton } from "@/components/auth/auth-layout";
import { useAuth } from "@/lib/auth";

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");

    const result = await login(email, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    router.push("/dashboard/home");
  }

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <AuthField
        label="Email address"
        name="email"
        type="email"
        placeholder="Enter your email"
        autoComplete="email"
      />
      <AuthField
        label="Password"
        name="password"
        type="password"
        placeholder="Enter your password"
        autoComplete="current-password"
        icon={<Eye className="h-4 w-4" />}
      />

      {error && (
        <p role="alert" className="rounded-md border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      )}

      <div className="flex items-center justify-between pt-1 text-xs">
        <label className="inline-flex items-center gap-2 text-white/60">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-white/20 bg-white/5 text-emerald-400 focus:ring-emerald-400/30"
          />
          Remember me
        </label>
        <a href="/forgot-password" className="text-emerald-300 hover:text-emerald-200">
          Forgot password?
        </a>
      </div>

      <AuthButton type="submit" className="mt-2" disabled={submitting}>
        {submitting ? "Signing in…" : "Sign In"}
      </AuthButton>

      <div className="mt-5">
        <AuthDivider label="or continue with" />
        <div className="mt-3 flex gap-3">
          <SocialAuthButton provider="Google" />
          <SocialAuthButton provider="Microsoft" />
        </div>
      </div>
    </form>
  );
}
