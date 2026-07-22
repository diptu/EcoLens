/**
 * PageHero — inner-page hero with breadcrumb, badge, headline, and
 * optional right-side visual. Used on /product, /resources, /solutions.
 *
 * Animations:
 *  - Framer Motion: word-reveal headline, stagger children
 *  - GSAP: optional parallax on the background image
 */
"use client";

import { m, useReducedMotion } from "framer-motion";
import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp, wordReveal } from "@/lib/animations";
import { prefersReducedMotion } from "@/lib/gsap";
import { ensureGsapRegistered } from "@/lib/gsap";
// Bypass gsap tree-shaking
import gsap from "gsap/dist/gsap.js";

export interface PageHeroProps {
  breadcrumb: Array<{ label: string; href?: string }>;
  badge: string;
  /** Headline. The first word(s) before the highlighted suffix are plain; the suffix is rendered with the gradient. */
  title: string;
  /** Highlighted suffix of the title (rendered with the lime→emerald gradient). */
  highlight?: string;
  subtitle: string;
  /** Optional right-side visual (image, illustration, dashboard mockup, etc.). */
  visual?: ReactNode;
  /** Optional micro-CTA row beneath the subtitle. */
  meta?: ReactNode;
}

export function PageHero({
  breadcrumb,
  badge,
  title,
  highlight,
  subtitle,
  visual,
  meta,
}: PageHeroProps) {
  const bgRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  // Subtle parallax on a background layer (decorative)
  useEffect(() => {
    if (!bgRef.current || reduce || prefersReducedMotion()) return;
    ensureGsapRegistered();
    const tween = gsap.to(bgRef.current, {
      yPercent: -10,
      ease: "none",
      scrollTrigger: { trigger: bgRef.current, start: "top top", end: "bottom top", scrub: true },
    });
    return () => {
      tween.kill();
    };
  }, [reduce]);

  return (
    <section className="relative isolate overflow-hidden pb-16 pt-10 md:pb-24 md:pt-16">
      {/* Decorative background layer */}
      <div
        ref={bgRef}
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse at 80% 0%, rgba(132,204,22,0.15) 0%, transparent 50%), radial-gradient(ellipse at 0% 100%, rgba(16,185,129,0.1) 0%, transparent 50%)",
        }}
      />

      <div className="mx-auto grid max-w-7xl items-center gap-12 px-6 md:grid-cols-2">
        <StaggerContainer className="flex flex-col">
          {/* Breadcrumb */}
          <MotionItem variant="fadeIn" className="flex items-center gap-1 text-sm text-white/60">
            {breadcrumb.map((crumb, i) => (
              <span key={i} className="flex items-center gap-1">
                {crumb.href ? (
                  <Link href={crumb.href} className="hover:text-white">
                    {crumb.label}
                  </Link>
                ) : (
                  <span className="text-white">{crumb.label}</span>
                )}
                {i < breadcrumb.length - 1 && <ChevronIcon />}
              </span>
            ))}
          </MotionItem>

          <MotionItem variant="fadeIn" className="mt-6">
            <Badge>{badge}</Badge>
          </MotionItem>

          <h1 className="mt-4 text-4xl font-extrabold leading-[1.1] tracking-tight text-white md:text-5xl lg:text-6xl">
            {highlight ? (
              <>
                {title}
                <span className="ml-2 bg-gradient-to-r from-lime-300 via-emerald-300 to-lime-300 bg-clip-text text-transparent">
                  {highlight}
                </span>
              </>
            ) : (
              <m.span variants={wordReveal} className="inline-block">
                {title}
              </m.span>
            )}
          </h1>

          <MotionItem variant="fadeUp">
            <p className="mt-6 max-w-lg text-base leading-relaxed text-white/70 md:text-lg">
              {subtitle}
            </p>
          </MotionItem>

          {meta && (
            <MotionItem variant="fadeUp">
              <div className="mt-6">{meta}</div>
            </MotionItem>
          )}
        </StaggerContainer>

        {visual && <div className="relative">{visual}</div>}
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
        <svg viewBox="0 0 8 8" fill="currentColor" className="h-2.5 w-2.5">
          <path d="M4 0L4.6 3.4L8 4L4.6 4.6L4 8L3.4 4.6L0 4L3.4 3.4Z" />
        </svg>
      </span>
      {String(children).toUpperCase()}
    </m.span>
  );
}

function ChevronIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-white/40">
      <path d="M4 2L8 6L4 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
