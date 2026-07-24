/**
 * CtaBanner — the bottom-of-page CTA with a forest background.
 * Used on /product and /solutions.
 */
"use client";

import Image from "next/image";
import { m, useReducedMotion } from "framer-motion";
import { useEffect, useRef, type ReactNode } from "react";

import { MotionButton } from "@/components/motion/motion-button";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp } from "@/lib/animations";
import { ensureGsapRegistered, prefersReducedMotion } from "@/lib/gsap";
import gsap from "gsap/dist/gsap.js";

export interface CtaBannerProps {
  badge?: string;
  heading: ReactNode;
  highlight?: ReactNode;
  body?: string;
  primary: { label: string; onClick?: () => void; href?: string };
  secondary?: { label: string; onClick?: () => void; href?: string };
  features?: string[];
  /** "hero" uses a full-bleed forest bg; "minimal" is plain. */
  variant?: "hero" | "minimal";
}

export function CtaBanner({
  badge,
  heading,
  highlight,
  body,
  primary,
  secondary,
  features,
  variant = "hero",
}: CtaBannerProps) {
  const bgRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  // Subtle parallax on the forest background
  useEffect(() => {
    if (!bgRef.current || reduce || prefersReducedMotion() || variant !== "hero") return;
    ensureGsapRegistered();
    const tween = gsap.to(bgRef.current, {
      yPercent: 8,
      ease: "none",
      scrollTrigger: { trigger: bgRef.current, start: "top bottom", end: "bottom top", scrub: true },
    });
    return () => {
      tween.kill();
    };
  }, [reduce, variant]);

  return (
    <section className="relative isolate overflow-hidden py-20 md:py-28">
      {variant === "hero" && (
        <>
          <div
            ref={bgRef}
            aria-hidden="true"
            className="absolute inset-0 -z-10 will-change-transform"
          >
            <Image
              src="/images/forest.webp"
              alt=""
              width={1400}
              height={900}
              className="h-full w-full object-cover opacity-50"
            />
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{
                background:
                  "linear-gradient(180deg, rgba(5,10,8,0.6) 0%, rgba(5,10,8,0.92) 70%, #050a08 100%)",
              }}
            />
          </div>
        </>
      )}

      <StaggerContainer className="relative z-10 mx-auto grid max-w-7xl items-center gap-10 px-6 md:grid-cols-2">
        <MotionItem variant="fadeUp">
          {badge && <CenterBadge>{badge}</CenterBadge>}
          <h2 className="mt-3 text-3xl font-bold leading-tight text-white md:text-4xl">
            {heading}
            {highlight}
          </h2>
          {body && (
            <p className="mt-3 max-w-md text-base leading-relaxed text-white/70">{body}</p>
          )}
        </MotionItem>

        <MotionItem variant="fadeUp" className="flex flex-col items-start gap-6 md:items-end">
          <div className="flex flex-col gap-3 sm:flex-row">
            <MotionButton size="lg" iconAfter={<ArrowRight />}>{primary.label}</MotionButton>
            {secondary && (
              <MotionButton size="lg" variant="secondary" iconAfter={<PlayIcon />}>
                {secondary.label}
              </MotionButton>
            )}
          </div>
          {features && features.length > 0 && (
            <ul className="grid gap-2 text-sm text-white/70 md:text-right">
              {features.map((f) => (
                <li key={f} className="flex items-center gap-2 md:justify-end">
                  <CheckIcon /> {f}
                </li>
              ))}
            </ul>
          )}
        </MotionItem>
      </StaggerContainer>
    </section>
  );
}

/* ─────────────────  Sub-components  ───────────────── */

function CenterBadge({ children }: { children: React.ReactNode }) {
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

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-emerald-400">
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
