/**
 * FeatureGrid — a card grid (icon, title, body, optional bullet list, and
 * an optional decorative right-side visual). Used on /blog.
 *
 * Animations: Framer Motion stagger entrance + hover lift.
 */
"use client";

import { m } from "framer-motion";
import { type ReactNode } from "react";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { cardHover, fadeUp } from "@/lib/animations";

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
              className="group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] p-6 transition-colors hover:border-emerald-200/30"
            >
              <div className="flex items-center gap-2">
                <m.span
                  variants={cardHover}
                  initial="rest"
                  whileHover="hover"
                  animate="rest"
                  className="grid h-9 w-9 place-items-center rounded-md border border-emerald-200/20 bg-emerald-200/10 text-emerald-100"
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

function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      className="mt-0.5 shrink-0 text-emerald-200"
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

