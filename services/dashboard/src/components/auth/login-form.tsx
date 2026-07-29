"use client";

/**
 * LoginForm — client component that handles the actual sign-in.
 *
 * Wires up:
 *  - form state (email, password, show/hide password)
 *  - submit handler calling `signIn()` from @/lib/auth
 *  - inline error messaging
 *  - loading spinner during the (mock) network call
 *  - localStorage session persistence
 *  - post-success redirect to /dashboard/home
 *
 * The form still uses the same AuthField/AuthButton primitives
 * as the rest of the auth pages so the visual stays consistent.
 */
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Eye, EyeOff, AlertCircle, Loader2 } from "lucide-react";

import { AuthField, AuthButton, AuthDivider, SocialAuthButton, AuthFooter } from "@/components/auth/auth-layout";
import { persistSession, reasonText, signIn, type SignInFailureReason } from "@/lib/auth";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; reason: SignInFailureReason };

export function LoginForm() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("diptu@ecolens.app");
  const [password, setPassword] = useState("Hello123");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (status.kind === "loading") return; // guard against double-submit
    setStatus({ kind: "loading" });
    const result = await signIn(identifier, password);
    if (!result.ok) {
      setStatus({ kind: "error", reason: result.reason });
      return;
    }
    persistSession(result.session);
    // Replace so the back button doesn't bring the form back
    router.replace("/dashboard/executive");
  }

  const isLoading = status.kind === "loading";
  const errorMessage = status.kind === "error" ? reasonText(status.reason) : null;

  return (
    <>
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <AuthField
          label="Email or username"
          name="identifier"
          type="text"
          placeholder="diptu@ecolens.app"
          autoComplete="username"
          value={identifier}
          onChange={(e) => setIdentifier(e.currentTarget.value)}
          required
          disabled={isLoading}
        />
        <AuthField
          label="Password"
          name="password"
          type={showPassword ? "text" : "password"}
          placeholder="Enter your password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          required
          disabled={isLoading}
          icon={
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="pointer-events-auto relative z-10 text-white/40 hover:text-white/80"
              aria-label={showPassword ? "Hide password" : "Show password"}
              data-testid="toggle-password-visibility"
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          }
        />

        <div className="flex items-center justify-between pt-1 text-xs">
          <label className="inline-flex items-center gap-2 text-white/60">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.currentTarget.checked)}
              className="h-3.5 w-3.5 rounded border-white/20 bg-white/5 text-emerald-200 focus:ring-emerald-200/30"
            />
            Remember me
          </label>
          <a href="/forgot-password" className="text-emerald-100 hover:text-emerald-100">
            Forgot password?
          </a>
        </div>

        {errorMessage && (
          <div
            role="alert"
            data-testid="login-error"
            className="flex items-start gap-2 rounded-md border border-red-400/20 bg-red-500/10 px-3 py-2 text-xs text-red-200"
          >
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        <AuthButton type="submit" className="mt-2" disabled={isLoading} data-testid="login-submit">
          {isLoading ? (
            <span className="inline-flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Signing in…
            </span>
          ) : (
            "Sign In"
          )}
        </AuthButton>
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
            <path
              fill="currentColor"
              d="M12 2 4 6v6c0 4.4 3.6 8.5 8 10 4.4-1.5 8-5.6 8-10V6l-8-4Zm0 2.2 6 3v4.8c0 3.4-2.7 6.6-6 7.8-3.3-1.2-6-4.4-6-7.8V7.2l6-3Z"
            />
          </svg>
          SSO / SAML
        </button>
      </div>

      <AuthFooter text="Don't have an account?" linkLabel="Sign up" linkHref="/signup" />

      {/* Demo hint — shown below the form so testers see the credentials
          without having to look at the source. Hidden in production builds
          via a build-time env flag if/when we add one. */}
      <div className="mt-6 rounded-md border border-emerald-200/15 bg-emerald-300/5 px-3 py-2 text-[11px] text-emerald-100/70">
        <p className="font-medium text-emerald-100/90">Demo credentials</p>
        <p className="mt-0.5">
          Username <code className="rounded bg-black/30 px-1 py-0.5 font-mono">diptu</code> ·
          password <code className="rounded bg-black/30 px-1 py-0.5 font-mono">Hello123</code>
        </p>
      </div>
    </>
  );
}
