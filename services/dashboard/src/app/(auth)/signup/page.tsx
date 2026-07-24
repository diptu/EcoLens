/**
 * /signup — Create your account.
 * Two-panel layout: feature list + eco illustration on the left, signup form on the right.
 */
import {
  AuthLayout,
  AuthHeader,
  AuthFooter,
} from "@/components/auth/auth-layout";
import { SignupForm } from "@/components/auth/signup-form";

const FEATURES = [
  {
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <path d="M4 19V5l8-2 8 2v14l-8 2-8-2Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M12 3v18" stroke="currentColor" strokeWidth="1.5" />
        <path d="M4 9l8 2 8-2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
    title: "Measure",
    sub: "Track and measure your emissions",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="m9 12 2 2 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
    title: "Reduce",
    sub: "Get AI-powered recommendations",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <path d="M6 3h9l5 5v13H6Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M15 3v5h5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M9 13h6M9 17h6" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
    title: "Report",
    sub: "Generate reports and stay compliant",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <path d="M3 12a9 9 0 1 1 18 0 9 9 0 0 1-18 0Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M12 7v5l3 2" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
    title: "Improve",
    sub: "Drive real impact over time",
  },
];

export const metadata = {
  title: "Sign up — EcoLens",
  description: "Create your EcoLens account and start your sustainability journey.",
};

export default function SignupPage() {
  return (
    <AuthLayout
      illustration="eco"
      tagline={<>Sustainability starts with action.</>}
      subTagline="Join thousands of organizations reducing their carbon footprint with EcoLens."
      topSlot={
        <ul className="space-y-2.5 text-left">
          {FEATURES.map((f) => (
            <li key={f.title} className="flex items-start gap-3 rounded-md border border-white/5 bg-white/[0.03] p-2.5">
              <span className="mt-0.5 grid h-7 w-7 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
                {f.icon}
              </span>
              <div>
                <p className="text-sm font-semibold text-white">{f.title}</p>
                <p className="text-[11px] text-white/60">{f.sub}</p>
              </div>
            </li>
          ))}
        </ul>
      }
    >
      <AuthHeader title="Create your account" breadcrumb={{ label: "/signup", href: "/signup" }} />
      <p className="-mt-4 mb-5 text-sm text-white/60">
        Join EcoLens and start your sustainability journey.
      </p>

      <SignupForm />

      <AuthFooter text="Already have an account?" linkLabel="Login" linkHref="/login" />
    </AuthLayout>
  );
}
