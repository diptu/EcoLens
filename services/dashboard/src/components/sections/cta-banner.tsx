/**
 * CtaBanner — the bottom-of-page CTA banner. Used on /resources and /blog.
 */
"use client";

import { m } from "framer-motion";
import type { ReactNode } from "react";

import { MotionButton } from "@/components/motion/motion-button";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp } from "@/lib/animations";

export interface CtaBannerProps {
  badge?: string;
  heading: ReactNode;
  highlight?: ReactNode;
  body?: string;
  primary?: { label: string; onClick?: () => void; href?: string };
  secondary?: { label: string; onClick?: () => void; href?: string };
  features?: string[];
}

export function CtaBanner({
  badge,
  heading,
  highlight,
  body,
  primary,
  secondary,
  features,
}: CtaBannerProps) {
  return (
    <section className="relative isolate overflow-hidden py-20 md:py-28">
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
          {primary && (
            <div className="flex flex-col gap-3 sm:flex-row">
              <MotionButton size="lg" iconAfter={<ArrowRight />}>{primary.label}</MotionButton>
              {secondary && (
                <MotionButton size="lg" variant="secondary" iconAfter={<PlayIcon />}>
                  {secondary.label}
                </MotionButton>
              )}
            </div>
          )}
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
      className="inline-flex items-center gap-2 rounded-full border border-emerald-200/30 bg-emerald-200/10 px-3 py-1 text-xs font-medium tracking-wider text-emerald-100"
    >
      <span className="grid h-4 w-4 place-items-center rounded-full bg-emerald-200/20">
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
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-emerald-200">
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
