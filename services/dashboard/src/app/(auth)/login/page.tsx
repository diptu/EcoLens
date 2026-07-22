/**
 * /login — Sign in form.
 * Two-panel layout: forest image + tagline on the left, form on the right.
 */
import { Eye } from "lucide-react";

import {
  AuthLayout,
  AuthField,
  AuthButton,
  AuthDivider,
  SocialAuthButton,
  AuthHeader,
  AuthFooter,
} from "@/components/auth/auth-layout";

export const metadata = {
  title: "Log in — EcoLens",
  description: "Access your EcoLens sustainability dashboard.",
};

export default function LoginPage() {
  return (
    <AuthLayout
      illustration="eco"
      tagline={<>Welcome back 👋</>}
      subTagline="Sign in to continue to your account and manage your sustainability impact."
    >
      <AuthHeader title="Login" breadcrumb={{ label: "/login", href: "/login" }} />

      <form className="space-y-4">
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

        <AuthButton type="submit" className="mt-2">Sign In</AuthButton>
      </form>

      <div className="mt-5">
        <AuthDivider label="or continue with" />
        <div className="mt-3 flex gap-3">
          <SocialAuthButton provider="Google" />
          <SocialAuthButton provider="Microsoft" />
        </div>
        <button
          type="button"
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-xs font-medium text-white/80 hover:bg-white/[0.07] hover:text-white"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
            <path fill="currentColor" d="M12 2 4 6v6c0 4.4 3.6 8.5 8 10 4.4-1.5 8-5.6 8-10V6l-8-4Zm0 2.2 6 3v4.8c0 3.4-2.7 6.6-6 7.8-3.3-1.2-6-4.4-6-7.8V7.2l6-3Z" />
          </svg>
          SSO / SAML
        </button>
      </div>

      <AuthFooter text="Don't have an account?" linkLabel="Sign up" linkHref="/signup" />
    </AuthLayout>
  );
}
