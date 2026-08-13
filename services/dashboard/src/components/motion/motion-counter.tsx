/**
 * Animated counter — vanilla requestAnimationFrame-based.
 * Reusable for any "1,250+ stats" display. No GSAP dependency.
 *
 * Uses IntersectionObserver to only start counting when the
 * element scrolls into view, easing with easeOutCubic.
 */
"use client";

import { useEffect, useRef } from "react";

export interface MotionCounterProps {
  /** Target value (the number to count up to). */
  value: number;
  /** Number of decimal places. Default 0. */
  decimals?: number;
  /** Text shown before the number. */
  prefix?: string;
  /** Text shown after the number (e.g. "+", "%", "M+"). */
  suffix?: string;
  /** Optional formatter for non-numeric styling (e.g. thousand separators). */
  format?: (n: number) => string;
  /** Duration of the count-up animation in seconds. */
  duration?: number;
  className?: string;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

export function MotionCounter({
  value,
  decimals = 0,
  prefix = "",
  suffix = "",
  format,
  duration = 2,
  className,
}: MotionCounterProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const hasRunRef = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Final value (used in reduced-motion mode and as the end state)
    const renderValue = (n: number) => {
      el.textContent = format
        ? `${prefix}${format(n)}${suffix}`
        : `${prefix}${n.toFixed(decimals)}${suffix}`;
    };

    if (prefersReducedMotion()) {
      renderValue(value);
      return;
    }

    const animate = () => {
      if (hasRunRef.current) return;
      hasRunRef.current = true;
      const start = performance.now();
      const tick = (now: number) => {
        const elapsed = (now - start) / 1000;
        const t = Math.min(elapsed / duration, 1);
        const eased = easeOutCubic(t);
        renderValue(value * eased);
        if (t < 1) {
          requestAnimationFrame(tick);
        } else {
          renderValue(value);
        }
      };
      requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            animate();
            observer.disconnect();
          }
        });
      },
      { threshold: 0.2 },
    );
    observer.observe(el);

    return () => {
      observer.disconnect();
    };
  }, [value, decimals, prefix, suffix, format, duration]);

  // Initial render (before animation starts) shows "0"
  const initial = format
    ? `${prefix}${format(0)}${suffix}`
    : `${prefix}${(0).toFixed(decimals)}${suffix}`;

  return (
    <span ref={ref} className={className} suppressHydrationWarning>
      {initial}
    </span>
  );
}

/** A "1,250" style formatter (thousand separators). */
export const formatThousands = (n: number): string =>
  Math.round(n).toLocaleString("en-US");

/** A "2.4M" style formatter (compact). */
export const formatCompact = (n: number): string => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return Math.round(n).toString();
};
