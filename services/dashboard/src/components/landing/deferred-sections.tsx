/**
 * `ssr: false` on `next/dynamic` is only allowed from a Client Component
 * (Next.js 16 App Router) — `landing-page.tsx` is deliberately kept a
 * Server Component (see its own docstring), so the below-the-fold
 * deferred-load wiring lives here instead, one thin client boundary
 * that just re-exports each section as a dynamic, no-SSR component.
 * The sections themselves are already client components (GSAP-driven
 * animations); this only defers *loading* them until after first paint.
 */
"use client";

import dynamic from "next/dynamic";

export const FeaturesGlobe = dynamic(
  () => import("@/components/landing/features-globe").then((m) => m.FeaturesGlobe),
  { ssr: false },
);
export const FeaturesRow = dynamic(
  () => import("@/components/landing/features-row").then((m) => m.FeaturesRow),
  { ssr: false },
);
export const TrustedBy = dynamic(
  () => import("@/components/landing/trusted-by").then((m) => m.TrustedBy),
  { ssr: false },
);
export const CtaSection = dynamic(
  () => import("@/components/landing/cta-section").then((m) => m.CtaSection),
  { ssr: false },
);
export const Footer = dynamic(
  () => import("@/components/landing/footer").then((m) => m.Footer),
  { ssr: false },
);
