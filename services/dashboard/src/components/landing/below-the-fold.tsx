"use client";

/**
 * Below-the-fold landing sections, dynamically imported with `ssr: false`
 * so they load on idle after first paint instead of blocking the LCP.
 * `ssr: false` requires a Client Component, hence this wrapper module.
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
