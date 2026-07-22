/**
 * FeatureGrid — the 6-card "Everything you need to drive real impact" grid
 * used on /product. Each card has an icon, title, body, bullet list, and
 * a decorative right-side visual (CSS or image).
 *
 * Animations:
 *  - Framer Motion: stagger entrance, hover lift
 *  - GSAP:        optional continuous orbit on the visuals
 */
"use client";

import { m, useReducedMotion } from "framer-motion";
import { useEffect, useRef, type ReactNode } from "react";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { cardHover, fadeUp } from "@/lib/animations";
import { ensureGsapRegistered, prefersReducedMotion } from "@/lib/gsap";
import gsap from "gsap/dist/gsap.js";

export interface FeatureGridItem {
  title: string;
  body: string;
  bullets?: string[];
  icon: ReactNode;
  /** Decorative right-side visual (CSS or image) */
  visual: ReactNode;
}

export interface FeatureGridProps {
  badge?: string;
  heading: ReactNode;
  subtitle?: string;
  items: FeatureGridItem[];
  /** Columns per row on desktop: 3 (default) or 2. */
  columns?: 2 | 3;
  className?: string;
}

export function FeatureGrid({
  badge,
  heading,
  subtitle,
  items,
  columns = 3,
  className,
}: FeatureGridProps) {
  const colClass = columns === 2 ? "lg:grid-cols-2" : "lg:grid-cols-3";

  return (
    <section className={className ?? "py-20 md:py-24"}>
      <div className="mx-auto max-w-7xl px-6">
        {(badge || heading) && (
          <StaggerContainer className="mx-auto mb-12 max-w-2xl text-center">
            {badge && (
              <MotionItem variant="fadeIn">
                <CenterBadge>{badge}</CenterBadge>
              </MotionItem>
            )}
            <MotionItem variant="fadeUp">
              <h2 className="mt-4 text-3xl font-bold leading-tight text-white md:text-4xl">
                {heading}
              </h2>
            </MotionItem>
            {subtitle && (
              <MotionItem variant="fadeUp">
                <p className="mt-3 text-white/60">{subtitle}</p>
              </MotionItem>
            )}
          </StaggerContainer>
        )}

        <StaggerContainer
          className={`grid grid-cols-1 gap-6 md:grid-cols-2 ${colClass}`}
          staggerDelay={0.08}
        >
          {items.map((item) => (
            <MotionItem
              key={item.title}
              variant="fadeUp"
              className="group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] p-6 transition-colors hover:border-emerald-400/30"
            >
              <div className="flex items-center gap-2">
                <m.span
                  variants={cardHover}
                  initial="rest"
                  whileHover="hover"
                  animate="rest"
                  className="grid h-9 w-9 place-items-center rounded-md border border-emerald-400/20 bg-emerald-400/10 text-emerald-300"
                >
                  {item.icon}
                </m.span>
                <h3 className="text-lg font-semibold text-white">{item.title}</h3>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-white/60">{item.body}</p>
              {item.bullets && item.bullets.length > 0 && (
                <ul className="mt-4 space-y-2">
                  {item.bullets.map((b) => (
                    <li key={b} className="flex items-start gap-2 text-sm text-white/80">
                      <CheckIcon />
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
              )}
              {item.visual && (
                <div className="mt-6 flex h-32 items-center justify-center">
                  {item.visual}
                </div>
              )}
            </MotionItem>
          ))}
        </StaggerContainer>
      </div>
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

function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      className="mt-0.5 shrink-0 text-emerald-400"
    >
      <circle cx="8" cy="8" r="7" stroke="currentColor" strokeOpacity="0.3" strokeWidth="1.4" />
      <path
        d="M4.5 8.2L7 10.5L11.5 5.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ─────────────────  Decorative visuals (reusable)  ───────────────── */

/** A CSS-only "funnel" visualisation — used for the Smart Data Ingestion card. */
export function FunnelVisual() {
  return (
    <div className="relative h-28 w-44">
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(circle at 50% 100%, rgba(132,204,22,0.4), transparent 60%)",
        }}
      />
      <svg viewBox="0 0 200 120" className="relative h-full w-full">
        <defs>
          <linearGradient id="funnel" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(132,204,22,0.6)" />
            <stop offset="100%" stopColor="rgba(16,185,129,0.1)" />
          </linearGradient>
        </defs>
        <polygon points="20,20 180,20 130,80 130,110 70,110 70,80" fill="url(#funnel)" stroke="rgba(132,204,22,0.4)" />
        <circle cx="50" cy="20" r="6" fill="rgba(132,204,22,0.8)" />
        <circle cx="100" cy="20" r="6" fill="rgba(132,204,22,0.8)" />
        <circle cx="150" cy="20" r="6" fill="rgba(132,204,22,0.8)" />
        <circle cx="100" cy="60" r="4" fill="rgba(16,185,129,0.9)" />
      </svg>
    </div>
  );
}

/** A CSS-only "AI brain" visualisation — used for the AI-Powered Calculations card. */
export function BrainVisual() {
  return (
    <div className="relative h-28 w-28">
      <div
        className="absolute inset-0 animate-pulse rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(132,204,22,0.5) 0%, transparent 70%)",
        }}
      />
      <svg viewBox="0 0 100 100" className="relative h-full w-full">
        <defs>
          <radialGradient id="brain">
            <stop offset="0%" stopColor="rgba(132,204,22,0.8)" />
            <stop offset="100%" stopColor="rgba(16,185,129,0.2)" />
          </radialGradient>
        </defs>
        <circle cx="50" cy="50" r="35" fill="url(#brain)" />
        {Array.from({ length: 8 }).map((_, i) => {
          const angle = (i * Math.PI * 2) / 8;
          const x = 50 + Math.cos(angle) * 25;
          const y = 50 + Math.sin(angle) * 25;
          return <circle key={i} cx={x} cy={y} r="2" fill="rgba(132,204,22,0.9)" />;
        })}
      </svg>
    </div>
  );
}

/** A "Top Reduction Opportunities" mini-chart visual. */
export function ChartVisual() {
  return (
    <div className="relative h-28 w-44 rounded-lg border border-white/10 bg-[#0a1410]/80 p-3">
      <p className="text-[10px] uppercase tracking-wider text-white/60">Top Reduction Opportunities</p>
      <div className="mt-2 space-y-2">
        {[
          { label: "Optimize Logistics", value: 320, w: 0.95 },
          { label: "Switch to Green Energy", value: 280, w: 0.82 },
          { label: "Improve Efficiency", value: 190, w: 0.55 },
        ].map((row) => (
          <div key={row.label}>
            <div className="flex items-center justify-between text-[10px] text-white/70">
              <span>{row.label}</span>
              <span className="tabular-nums">{row.value} tCO₂e</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/5">
              <div
                className="h-full rounded-full bg-gradient-to-r from-lime-300 to-emerald-400"
                style={{ width: `${row.w * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** A "Goal Progress" donut visual. */
export function DonutVisual({ percent = 72 }: { percent?: number }) {
  const r = 28;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative h-28 w-28">
      <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90">
        <circle cx="40" cy="40" r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="6" />
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke="url(#donutGrad)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - percent / 100)}
        />
        <defs>
          <linearGradient id="donutGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="rgba(132,204,22,1)" />
            <stop offset="100%" stopColor="rgba(16,185,129,1)" />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold text-white">{percent}%</span>
        <span className="text-[10px] text-emerald-300">On Track</span>
      </div>
    </div>
  );
}

/** An "ESG Report" document visual. */
export function ReportVisual() {
  return (
    <div className="relative h-28 w-36">
      <div
        className="absolute right-2 top-2 h-full w-full rounded-md border border-white/10 bg-white/[0.04]"
        style={{ background: "linear-gradient(135deg, rgba(16,185,129,0.1), rgba(0,0,0,0))" }}
      />
      <div className="relative h-full w-full rounded-md border border-emerald-400/20 bg-[#0a1410] p-3">
        <p className="text-[10px] uppercase tracking-wider text-emerald-300">ESG Report</p>
        <div className="mt-2 space-y-1">
          <div className="h-1 w-3/4 rounded bg-white/10" />
          <div className="h-1 w-2/3 rounded bg-white/10" />
          <div className="h-1 w-1/2 rounded bg-white/10" />
        </div>
        <LeafDecoration />
      </div>
    </div>
  );
}

function LeafDecoration() {
  return (
    <svg viewBox="0 0 24 24" fill="rgba(132,204,22,0.4)" className="absolute bottom-2 right-2 h-6 w-6">
      <path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" />
    </svg>
  );
}

/** A "Reduce & Offset" wind turbine visual. */
export function WindTurbineVisual() {
  return (
    <div className="relative h-28 w-44">
      <svg viewBox="0 0 100 60" className="h-full w-full">
        <line x1="50" y1="60" x2="50" y2="20" stroke="rgba(255,255,255,0.4)" strokeWidth="2" />
        <g style={{ transformOrigin: "50px 20px", animation: "spin 4s linear infinite" }}>
          <ellipse cx="50" cy="10" rx="3" ry="14" fill="rgba(255,255,255,0.85)" />
          <ellipse cx="50" cy="10" rx="3" ry="14" fill="rgba(255,255,255,0.85)" transform="rotate(120 50 20)" />
          <ellipse cx="50" cy="10" rx="3" ry="14" fill="rgba(255,255,255,0.85)" transform="rotate(240 50 20)" />
        </g>
        <circle cx="50" cy="20" r="2" fill="rgba(255,255,255,0.95)" />
      </svg>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
