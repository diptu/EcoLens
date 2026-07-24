/**
 * /login — Sign in form.
 * Two-panel layout: forest image + tagline on the left, form on the right.
 */
import {
  AuthLayout,
  AuthHeader,
  AuthFooter,
} from "@/components/auth/auth-layout";
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

      <AuthFooter text="Don&apos;t have an account?" linkLabel="Sign up" linkHref="/signup" />
    </AuthLayout>
  );
}
