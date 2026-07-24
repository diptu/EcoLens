/**
 * "From Data to Decarbonization" — copy on the left, a stylized
 * globe on the right with 4 feature cards orbiting it.
 *
 * Animations:
 *  - Framer Motion: cards enter staggered; hover lift on cards
 *  - GSAP:         globe continuous slow rotation (paused with
 *                   reduced motion)
 */
"use client";

import { m, useReducedMotion } from "framer-motion";
import { useEffect, useRef } from "react";

import { MotionButton } from "@/components/motion/motion-button";
import { AnimatedSection, MotionItem, StaggerContainer } from "@/components/motion/motion-section";
import { fadeUp, cardHover } from "@/lib/animations";
import { ensureGsapRegistered, prefersReducedMotion } from "@/lib/gsap";
// Direct import path bypasses gsap's "sideEffects": false tree-shaking
import gsap from "gsap/dist/gsap.js";

interface Feature {
  title: string;
  body: string;
  icon: React.ReactNode;
  position: "tl" | "tr" | "bl" | "br";
}

const FEATURES: Feature[] = [
  {
    title: "AI Insights",
    body: "Smart anomaly detection and recommendations",
    icon: <SparkleIcon />,
    position: "tl",
  },
  {
    title: "Automated Reports",
    body: "Framework-aligned reports in one click",
    icon: <ChartIcon />,
    position: "tr",
  },
  {
    title: "Real-time Tracking",
    body: "Monitor emissions across all operations",
    icon: <PulseIcon />,
    position: "bl",
  },
  {
    title: "Reduce & Offset",
    body: "Track reduction targets and offset impact",
    icon: <LeafIcon />,
    position: "br",
  },
];

const positionClasses: Record<Feature["position"], string> = {
  tl: "top-[6%] left-[2%]",
  tr: "top-[10%] right-[2%]",
  bl: "bottom-[12%] left-[2%]",
  br: "bottom-[8%] right-[2%]",
};

export function FeaturesGlobe() {
  const globeRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (!globeRef.current || reduce || prefersReducedMotion()) return;
    ensureGsapRegistered();
    const tween = gsap.to(globeRef.current, {
      rotate: 360,
      duration: 80,
      ease: "none",
      repeat: -1,
      transformOrigin: "50% 50%",
    });
    return () => {
      tween.kill();
    };
  }, [reduce]);

  return (
    <section className="relative py-24 md:py-32">
      <div className="mx-auto grid max-w-7xl items-center gap-12 px-6 md:grid-cols-2">
        {/* Left: copy */}
        <StaggerContainer className="flex flex-col">
          <MotionItem variant="fadeIn">
            <Badge>Built for impact</Badge>
          </MotionItem>

          <h2 className="mt-6 text-4xl font-bold leading-[1.1] tracking-tight text-white md:text-5xl">
            From Data to{" "}
            <span className="bg-gradient-to-r from-lime-300 to-emerald-300 bg-clip-text text-transparent">
              Decarbonization
            </span>
          </h2>

          <MotionItem variant="fadeUp">
            <p className="mt-6 max-w-md text-base leading-relaxed text-white/70 md:text-lg">
              EcoLens combines AI, automation, and scientific models to turn
              complex climate data into actionable strategy.
            </p>
          </MotionItem>

          <MotionItem variant="fadeUp">
            <div className="mt-8">
              <MotionButton variant="outline" iconAfter={<ArrowRight />}>
                Explore Features
              </MotionButton>
            </div>
          </MotionItem>
        </StaggerContainer>

        {/* Right: globe with feature cards */}
        <div className="relative aspect-square w-full">
          <div
            ref={globeRef}
            className="absolute inset-[18%] will-change-transform"
            aria-hidden="true"
          >
            {/* CSS-only "Earth" — concentric gradients, no external image */}
            <div
              className="h-full w-full rounded-full ring-1 ring-inset ring-emerald-300/30 will-change-transform"
              style={{
                background:
                  "radial-gradient(circle at 30% 30%, rgba(132,204,22,0.4) 0%, transparent 35%), radial-gradient(circle at 70% 60%, rgba(16,185,129,0.5) 0%, transparent 45%), radial-gradient(circle at 50% 50%, rgba(56,189,248,0.25) 0%, transparent 60%), #0a1410",
                boxShadow: "0 0 60px rgba(16,185,129,0.35), inset 0 0 40px rgba(56,189,248,0.2)",
              }}
            />
            {/* Continent-like dark patches to suggest Earth without a real image */}
            <div
              className="absolute inset-0 rounded-full opacity-30"
              style={{
                background:
                  "radial-gradient(ellipse at 35% 40%, rgba(0,0,0,0.5) 0%, transparent 25%), radial-gradient(ellipse at 60% 65%, rgba(0,0,0,0.4) 0%, transparent 20%), radial-gradient(ellipse at 75% 30%, rgba(0,0,0,0.4) 0%, transparent 18%)",
              }}
            />
          </div>

          {/* Orbit lines (decorative) */}
          <OrbitRings />

          {/* Feature cards positioned at the 4 corners */}
          <AnimatedSection className="absolute inset-0" stagger={true} staggerDelay={0.12}>
            {FEATURES.map((feature) => (
              <m.div
                key={feature.title}
                variants={fadeUp}
                initial="rest"
                whileHover="hover"
                animate="rest"
                className={`absolute ${positionClasses[feature.position]} w-44`}
              >
                <m.div
                  variants={cardHover}
                  className="group rounded-2xl border border-white/10 bg-[#0a1410]/80 p-4 backdrop-blur-md transition-colors hover:border-emerald-400/30"
                >
                  <div className="flex items-center gap-2">
                    <span className="grid h-7 w-7 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
                      {feature.icon}
                    </span>
                    <h3 className="text-sm font-semibold text-white">{feature.title}</h3>
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-white/60">
                    {feature.body}
                  </p>
                </m.div>
              </m.div>
            ))}
          </AnimatedSection>
        </div>
      </div>
    </section>
  );
}

/* ─────────────────  Sub-components  ───────────────── */

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <m.span
      variants={fadeUp}
      className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium tracking-wider text-emerald-300"
    >
      <FlameIcon className="h-3 w-3" />
      {String(children).toUpperCase()}
    </m.span>
  );
}

function OrbitRings() {
  return (
    <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
      <div className="absolute inset-[10%] rounded-full border border-dashed border-emerald-300/15" />
      <div className="absolute inset-[20%] rounded-full border border-dashed border-emerald-300/10" />
      <div className="absolute top-[12%] left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.7)]" />
      <div className="absolute bottom-[18%] right-[12%] h-2 w-2 rounded-full bg-lime-300 shadow-[0_0_12px_rgba(132,204,22,0.7)]" />
    </div>
  );
}

/* ─────────────────  Icons  ───────────────── */

function SparkleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
      <path d="M7 0L8 5L13 6L8 7L7 12L6 7L1 6L6 5L7 0Z" />
    </svg>
  );
}
function ChartIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M2 12V6M6 12V2M10 12V8" strokeLinecap="round" />
    </svg>
  );
}
function PulseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M1 7h3l1.5-3 3 6L10 7h3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function LeafIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
      <path d="M11 3C5 4 3 8 2 11l1 .4.6-1.4h.7c3 0 5.5-2.5 5.5-6.5V3h-.3c-.2 0-.3.1-.3.3 0 .1 0 .2.1.3L11 3z" />
    </svg>
  );
}
function FlameIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 12 12" fill="currentColor" className={className}>
      <path d="M6 1c-1 2-3 3-3 6 0 2 1.5 4 3 4s3-2 3-4c0-1.5-1-2-1-3.5C8 2 7 1 6 1z" />
    </svg>
  );
}
function ArrowRight() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path
        d="M2 6h7m0 0L6 3m3 3L6 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
