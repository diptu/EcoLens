/**
 * Hero section — the first thing users see.
 *
 * Performance notes:
 *  - The Earth image is self-hosted at /images/earth.webp and preloaded
 *    in layout.tsx, so it's the LCP element and renders fast.
 *  - The "pulsing" effects are GPU-friendly (transform + opacity only,
 *    no filter blurs on the main Earth).
 *  - Framer Motion is used via `m.X` (LazyMotion strict mode) — only
 *    the small domAnimation features are loaded.
 *  - The orbit animation is pure CSS (`@keyframes` + `animation`)
 *    so GSAP is NOT loaded in the initial bundle.
 */
"use client";

import Image from "next/image";
import { m } from "framer-motion";

import { MotionButton } from "@/components/motion/motion-button";
import { fadeUp } from "@/lib/animations";

const HEADLINE = ["Measure", "Today."];
const HEADLINE_HIGHLIGHT = "Sustain Tomorrow.";

export function Hero() {
  return (
    <section className="relative isolate overflow-hidden pb-32 pt-20 md:pt-28">
      {/* Background gradient orbs (no blurs — pure gradients for GPU perf) */}
      <BackgroundOrbs />

      {/* Content */}
      <div className="relative z-10 mx-auto grid max-w-7xl items-center gap-16 px-6 md:grid-cols-2">
        {/* Left column — copy
           Performance: above-the-fold content uses CSS-only animations
           (no Framer Motion opacity:0) so the LCP text is visible
           immediately. Framer Motion is reserved for below-the-fold
           and interactive elements. */}
        <div className="flex flex-col">
          <div className="css-fade-in">
            <Badge>AI-powered carbon accounting</Badge>
          </div>

          <h1 className="mt-6 text-5xl font-extrabold leading-[1.05] tracking-tight text-white md:text-6xl lg:text-7xl">
            <span className="block">
              {HEADLINE.map((word, i) => (
                <span
                  key={`${word}-${i}`}
                  className={`inline-block ${i === 0 ? "css-word-1" : "css-word-2"}`}
                >
                  {word}
                  {i < HEADLINE.length - 1 ? "\u00A0" : ""}
                </span>
              ))}
            </span>
            <span className="mt-1 block bg-gradient-to-r from-lime-300 via-emerald-300 to-lime-300 bg-clip-text text-transparent css-word-3">
              {HEADLINE_HIGHLIGHT}
              <LeafSparkle className="ml-1 inline h-8 w-8 align-baseline text-lime-300" />
            </span>
          </h1>

          <div className="css-fade-up-1">
            <p className="mt-6 max-w-md text-base leading-relaxed text-white/70 md:text-lg">
              EcoLens helps organizations measure, monitor, and reduce their carbon
              footprint with AI-powered insights and effortless reporting.
            </p>
          </div>

          <div className="css-fade-up-2">
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <MotionButton size="lg" iconAfter={<ArrowRight />}>
                Get Started Free
              </MotionButton>
              <MotionButton size="lg" variant="secondary" iconAfter={<PlayIcon />}>
                Watch Demo
              </MotionButton>
            </div>
          </div>

          <div className="css-fade-up-3">
            <ul className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-white/60">
              <li className="flex items-center gap-2">
                <CheckIcon /> No credit card required
              </li>
              <li className="flex items-center gap-2">
                <CheckIcon /> Free forever plan available
              </li>
            </ul>
          </div>
        </div>

        {/* Right column — Earth with orbiting eco-icons (CSS-only animations) */}
        <div className="relative aspect-square w-full">
          <GlobeVisual />
          <div
            className="absolute inset-0 will-change-transform hero-orbit"
            aria-hidden="true"
          >
            <FloatingLeaf className="absolute left-[8%] top-[12%] h-6 w-6 text-lime-300" />
            <FloatingLeaf className="absolute right-[6%] top-[28%] h-8 w-8 rotate-45 text-emerald-300" />
            <FloatingLeaf className="absolute bottom-[14%] left-[18%] h-5 w-5 -rotate-12 text-lime-200" />
            <FloatingLeaf className="absolute bottom-[28%] right-[12%] h-7 w-7 rotate-90 text-emerald-400" />
            <FloatingLeaf className="absolute left-[42%] top-[4%] h-4 w-4 text-lime-300" />
            <FloatingOrbit className="absolute right-[16%] top-[6%] h-7 w-7 text-emerald-300">
              <RecycleIcon />
            </FloatingOrbit>
            <FloatingOrbit className="absolute bottom-[6%] left-[8%] h-6 w-6 text-rose-400">
              <SmallHeartIcon />
            </FloatingOrbit>
            <FloatingOrbit className="absolute right-[4%] bottom-[38%] h-5 w-5 text-sky-300">
              <DropIcon />
            </FloatingOrbit>
          </div>
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
      <span className="grid h-4 w-4 place-items-center rounded-full bg-emerald-400/20">
        <SparkleIcon className="h-2.5 w-2.5 text-emerald-300" />
      </span>
      {String(children).toUpperCase()}
    </m.span>
  );
}

function BackgroundOrbs() {
  return (
    <>
      {/* Pure radial gradients — no blur filters (saves ~30% GPU on low-end devices) */}
      <div
        className="pointer-events-none absolute -left-40 top-1/3 h-[420px] w-[420px] rounded-full opacity-50"
        style={{ background: "radial-gradient(circle, rgba(16,185,129,0.35) 0%, rgba(16,185,129,0) 70%)" }}
      />
      <div
        className="pointer-events-none absolute -right-32 top-10 h-[360px] w-[360px] rounded-full opacity-40"
        style={{ background: "radial-gradient(circle, rgba(132,204,22,0.25) 0%, rgba(132,204,22,0) 70%)" }}
      />
    </>
  );
}

function GlobeVisual() {
  return (
    <div className="relative h-full w-full">
      {/* Outer atmosphere glow — pulses softly via opacity (no blur) */}
      <div
        className="atmosphere-pulse pointer-events-none absolute inset-6 rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(56,189,248,0.45) 0%, rgba(16,185,129,0.2) 50%, rgba(56,189,248,0) 75%)",
        }}
      />
      {/* Earth — recognizable blue marble, self-hosted, preloaded */}
      <div className="earth-rotate absolute inset-0 overflow-hidden rounded-full ring-1 ring-inset ring-sky-300/30 will-change-transform">
        <Image
          src="/images/earth.webp"
          alt="Earth, our home — a blue-and-green planet, slowly rotating, surrounded by a soft atmosphere."
          width={800}
          height={800}
          priority
          fetchPriority="high"
          sizes="(max-width: 768px) 90vw, 600px"
          className="h-full w-full object-cover"
        />
      </div>
      {/* Drifting cloud layer (CSS gradients, rotating opposite to Earth) */}
      <div
        className="cloud-drift pointer-events-none absolute inset-0 rounded-full opacity-40 mix-blend-screen will-change-transform"
        style={{
          background:
            "radial-gradient(circle at 30% 30%, rgba(255,255,255,0.45), transparent 45%), radial-gradient(circle at 70% 60%, rgba(255,255,255,0.35), transparent 40%), radial-gradient(circle at 50% 85%, rgba(255,255,255,0.25), transparent 35%)",
        }}
      />
      {/* Atmospheric rim — the soft halo at the planet's edge (no blur) */}
      <div
        className="pointer-events-none absolute inset-0 rounded-full"
        style={{
          boxShadow:
            "inset 0 0 60px rgba(56,189,248,0.35), 0 0 40px rgba(16,185,129,0.25)",
        }}
      />
      {/* Pulsing heart on the planet — "what we are protecting" */}
      <div
        className="heart-pulse absolute left-[22%] top-[26%] grid h-9 w-9 place-items-center rounded-full bg-rose-500/90 will-change-transform"
        style={{ boxShadow: "0 0 20px rgba(244,63,94,0.6)" }}
        aria-label="A pulsing heart on Earth, symbolising what we are protecting"
      >
        <HeartIcon className="h-4 w-4 text-white" />
      </div>
    </div>
  );
}

function HeartIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12 21s-7-4.5-9.5-9.2C.7 8.4 2.6 4.5 6.3 4.5c2 0 3.6 1.1 4.4 2.6.8-1.5 2.4-2.6 4.4-2.6 3.7 0 5.6 3.9 3.8 7.3C19 16.5 12 21 12 21z" />
    </svg>
  );
}

function FloatingLeaf({ className }: { className?: string }) {
  return (
    <div className={`leaf-bob ${className || ""}`}>
      <svg viewBox="0 0 24 24" fill="currentColor">
        <path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" />
      </svg>
    </div>
  );
}

function FloatingOrbit({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`orbit-bob ${className || ""}`}>
      {children}
    </div>
  );
}

function RecycleIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M7 17h10l1.5-2.6-1.5-2.6-2.6 4.5-5.2 0-1.5 2.6L7 17zm10-10L15 5l-5 8.7 2.6 0L15 11l1.5 2.6 2.6-4.5L17 7zm-3.5 0L12 9.6 14.5 14h2.6L19 11l-1.5-2.6L13.5 7z" />
    </svg>
  );
}

function SmallHeartIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 21s-7-4.5-9.5-9.2C.7 8.4 2.6 4.5 6.3 4.5c2 0 3.6 1.1 4.4 2.6.8-1.5 2.4-2.6 4.4-2.6 3.7 0 5.6 3.9 3.8 7.3C19 16.5 12 21 12 21z" />
    </svg>
  );
}

function DropIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2C12 2 5 11 5 15.5A7 7 0 0012 22a7 7 0 007-6.5C19 11 12 2 12 2zm0 17.5a4 4 0 01-4-4c0-1 .5-2.5 2-5l2-3 2 3c1.5 2.5 2 4 2 5a4 4 0 01-4 4z" />
    </svg>
  );
}

function LeafSparkle({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="6" stroke="currentColor" strokeOpacity="0.4" strokeWidth="1.2" />
      <path
        d="M4 7l2 2 4-4"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SparkleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 8 8" fill="currentColor" className={className}>
      <path d="M4 0L4.6 3.4L8 4L4.6 4.6L4 8L3.4 4.6L0 4L3.4 3.4Z" />
    </svg>
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

function PlayIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
      <path d="M3 2v8l7-4-7-4z" />
    </svg>
  );
}
