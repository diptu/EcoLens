/**
 * "Trusted by" — a row of customer logos. Each logo has a soft
 * hover scale + color desaturation lift.
 */
"use client";

import { m } from "framer-motion";

import { AnimatedSection, MotionItem, StaggerContainer } from "@/components/motion/motion-section";
import { fadeUp } from "@/lib/animations";

interface PartnerLogo {
  name: string;
  /** SVG icon to display (kept simple, monochrome). */
  icon: React.ReactNode;
  /** Optional subtitle for the brand. */
  subtitle?: string;
}

const PARTNERS: PartnerLogo[] = [
  { name: "GreenTech",     subtitle: "Solutions",   icon: <CloudLogo /> },
  { name: "TerraNova",     subtitle: "Energy",      icon: <BurstLogo /> },
  { name: "EcoMotion",     subtitle: "Logistics",   icon: <ArrowUpLogo /> },
  { name: "FutureBuild",   subtitle: "Developments", icon: <BoxLogo /> },
  { name: "PureHarvest",   subtitle: "Foods",        icon: <LeafLogo /> },
];

export function TrustedBy() {
  return (
    <section className="border-t border-white/5 py-16">
      <div className="mx-auto grid max-w-7xl items-center gap-8 px-6 md:grid-cols-3">
        <AnimatedSection variant="fadeUp" className="md:col-span-1">
          <h2 className="max-w-xs text-2xl font-semibold leading-snug text-white md:text-3xl">
            Trusted by{" "}
            <span className="text-white/60">organizations</span> committed to
            a <span className="text-lime-300">sustainable future</span>
          </h2>
        </AnimatedSection>

        <StaggerContainer
          className="grid grid-cols-2 items-center gap-x-6 gap-y-6 sm:grid-cols-3 md:col-span-2 md:grid-cols-5"
          stagger={true}
          staggerDelay={0.06}
          viewportAmount={0.5}
        >
          {PARTNERS.map((partner) => (
            <MotionItem
              key={partner.name}
              variant="fadeIn"
              className="group flex items-center gap-2 text-white/40 transition-colors hover:text-white/80"
            >
              <m.div
                whileHover={{ scale: 1.08 }}
                transition={{ type: "spring", stiffness: 300, damping: 15 }}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-md"
              >
                {partner.icon}
              </m.div>
              <div className="leading-tight">
                <p className="text-sm font-semibold text-current">{partner.name}</p>
                {partner.subtitle && (
                  <p className="text-[10px] uppercase tracking-wider text-current/60">
                    {partner.subtitle}
                  </p>
                )}
              </div>
            </MotionItem>
          ))}
        </StaggerContainer>
      </div>
    </section>
  );
}

/* ─────────────────  Logo placeholders (monochrome SVG)  ───────────────── */

function CloudLogo() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
      <path d="M7 18a4 4 0 010-8 6 6 0 0111.5 1.5A4 4 0 0118 18H7z" />
    </svg>
  );
}
function BurstLogo() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="22" height="22">
      <circle cx="12" cy="12" r="3" fill="currentColor" />
      <path d="M12 4v3M12 17v3M4 12h3M17 12h3M6.3 6.3l2 2M15.7 15.7l2 2M6.3 17.7l2-2M15.7 8.3l2-2" strokeLinecap="round" />
    </svg>
  );
}
function ArrowUpLogo() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
      <path d="M12 3l8 10h-5v8h-6v-8H4l8-10z" />
    </svg>
  );
}
function BoxLogo() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="22" height="22">
      <path d="M4 7l8-4 8 4-8 4-8-4z" strokeLinejoin="round" />
      <path d="M4 7v10l8 4 8-4V7" strokeLinejoin="round" />
    </svg>
  );
}
function LeafLogo() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22">
      <path d="M19 5C9 7 6 14 4 19l1.5.5.8-2c.6-.1 1.2 0 1.7 0 4.5 0 8-3.5 8-9V5h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L19 5z" />
    </svg>
  );
}
