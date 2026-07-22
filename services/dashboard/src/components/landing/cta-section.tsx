/**
 * Final CTA — a "Your sustainability journey starts here" section
 * with a centered get-started button. Big background gradient,
 * a soft "data viz" visual in the middle.
 */
"use client";

import { m } from "framer-motion";

import { MotionButton } from "@/components/motion/motion-button";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp } from "@/lib/animations";

export function CtaSection() {
  return (
    <section className="relative overflow-hidden py-24 md:py-32">
      {/* Soft glow */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-1/2 h-[500px] w-[800px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-500/15 blur-[140px]" />
      </div>

      <StaggerContainer className="relative z-10 mx-auto grid max-w-7xl items-center gap-10 px-6 md:grid-cols-2">
        {/* Left: copy + CTA */}
        <MotionItem variant="fadeUp" className="flex flex-col">
          <h2 className="text-4xl font-bold leading-[1.1] tracking-tight text-white md:text-5xl">
            Your sustainability journey
            <span className="mt-1 block bg-gradient-to-r from-lime-300 to-emerald-300 bg-clip-text text-transparent">
              starts here.
            </span>
          </h2>
          <p className="mt-6 max-w-md text-base leading-relaxed text-white/70 md:text-lg">
            Join thousands of organizations using EcoLens to build a cleaner,
            greener tomorrow.
          </p>
        </MotionItem>

        {/* Right: visual + CTA */}
        <MotionItem variant="fadeUp" className="flex flex-col items-start gap-8 md:items-end">
          <p className="text-2xl font-semibold leading-tight text-white md:text-right md:text-3xl">
            Start measuring
            <br />
            in <span className="text-lime-300">less than 5 minutes.</span>
          </p>
          <MotionButton size="lg" iconAfter={<ArrowRight />}>
            Get Started Free
          </MotionButton>
        </MotionItem>
      </StaggerContainer>

      {/* Centerpiece visual */}
      <m.div
        initial={{ opacity: 0, scale: 0.85 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, amount: 0.4 }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
        className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
      >
        <SproutVisual />
      </m.div>
    </section>
  );
}

/* ─────────────────  Sub-components  ───────────────── */

function SproutVisual() {
  return (
    <div className="relative h-48 w-48 opacity-30">
      <div className="absolute inset-0 rounded-full bg-emerald-400/30 blur-3xl" />
      <svg viewBox="0 0 100 100" className="relative h-full w-full">
        <defs>
          <radialGradient id="globe" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#84cc16" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="50" cy="50" r="40" fill="url(#globe)" />
        <path
          d="M50 75 C 40 70, 35 60, 40 50 C 45 40, 55 45, 55 35 C 60 30, 65 35, 60 45"
          fill="none"
          stroke="#84cc16"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <ellipse cx="44" cy="42" rx="6" ry="3" fill="#84cc16" transform="rotate(-30 44 42)" />
        <ellipse cx="60" cy="38" rx="6" ry="3" fill="#84cc16" transform="rotate(30 60 38)" />
      </svg>
    </div>
  );
}

function ArrowRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path
        d="M3 7h8m0 0L8 4m3 3L8 10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
