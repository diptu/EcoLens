"use client";

/**
 * `next/dynamic` with `{ ssr: false }` is only allowed in a Client
 * Component (Next.js App Router). `landing-page.tsx` stays a Server
 * Component, so the below-the-fold dynamic imports live here instead.
 */
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
