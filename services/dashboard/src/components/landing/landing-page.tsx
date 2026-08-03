/**
 * Landing page composition — a server component (no client JS
 * at the top level) that just lays out the sections. Each
 * section is its own client component that owns its animations.
 *
 * Performance: Hero + StatsBar render in the initial bundle (above
 * the fold). The StatsBar counter is vanilla (requestAnimationFrame)
 * — no GSAP needed for the initial page. Everything below the fold
 * is dynamically imported so it loads after first paint and doesn't
 * block the LCP.
 */
import dynamic from "next/dynamic";

import { Hero } from "@/components/landing/hero";
import { Navbar } from "@/components/landing/navbar";
import { StatsBar } from "@/components/landing/stats-bar";
import { MotionProvider } from "@/components/motion/motion-provider";

// Below-the-fold sections — load on idle so the initial paint is fast
const FeaturesGlobe = dynamic(
  () => import("@/components/landing/features-globe").then((m) => m.FeaturesGlobe),
  { ssr: false },
);
const FeaturesRow = dynamic(
  () => import("@/components/landing/features-row").then((m) => m.FeaturesRow),
  { ssr: false },
);
const TrustedBy = dynamic(
  () => import("@/components/landing/trusted-by").then((m) => m.TrustedBy),
  { ssr: false },
);
const CtaSection = dynamic(
  () => import("@/components/landing/cta-section").then((m) => m.CtaSection),
  { ssr: false },
);
const Footer = dynamic(
  () => import("@/components/landing/footer").then((m) => m.Footer),
  { ssr: false },
);

export function LandingPage() {
  return (
    <MotionProvider>
      <div className="min-h-screen bg-[#050a08] text-white">
        <Navbar />
        <main>
          <Hero />
          <StatsBar />
          <FeaturesGlobe />
          <FeaturesRow />
          <TrustedBy />
          <CtaSection />
        </main>
        <Footer />
      </div>
    </MotionProvider>
  );
}
