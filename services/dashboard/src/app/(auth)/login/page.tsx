/**
 * /login — Sign in form.
 * Two-panel layout: forest image + tagline on the left, form on the right.
 *
 * The interactive part is in <LoginForm /> (a client component);
 * this page is the server-rendered shell.
 */
import { AuthLayout, AuthHeader } from "@/components/auth/auth-layout";
import { LoginForm } from "@/components/auth/login-form";

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
      <LoginForm />
    </AuthLayout>
  );
}
