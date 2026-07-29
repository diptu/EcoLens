/**
 * Reusable Framer Motion variants + utility helpers.
 * Every animated section/page should use a variant from this file so
 * timing, easing, and stagger feel consistent across the site.
 */
import type { Variants, Transition, Easing } from "framer-motion";

/* ──────────────────────────  Easings  ────────────────────────── */
const EASE_OUT_EXPO: Easing = [0.16, 1, 0.3, 1];      // hero, big reveals
const EASE_OUT_QUART: Easing = [0.25, 1, 0.5, 1];     // cards, lists
const EASE_IN_OUT: Easing = [0.65, 0, 0.35, 1];       // toggles, modals

/* ──────────────────────────  Transitions  ───────────────────── */
export const transitions = {
  fast:    { duration: 0.2, ease: EASE_OUT_QUART } satisfies Transition,
  normal:  { duration: 0.4, ease: EASE_OUT_QUART } satisfies Transition,
  slow:    { duration: 0.7, ease: EASE_OUT_EXPO } satisfies Transition,
  hero:    { duration: 0.9, ease: EASE_OUT_EXPO } satisfies Transition,
  modal:   { duration: 0.3, ease: EASE_IN_OUT } satisfies Transition,
} as const;

/* ──────────────────────────  Variants  ──────────────────────── */

/** Parent variant — stagger children. */
export const staggerContainer: Variants = {
  hidden:  { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.15,
    },
  },
};

/** Child variant — fade + slide up. */
export const fadeUp: Variants = {
  hidden:  { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: transitions.slow,
  },
};

/** Fade in only (for images / media). */
export const fadeIn: Variants = {
  hidden:  { opacity: 0 },
  visible: { opacity: 1, transition: transitions.slow },
};

/** Scale up from a slight zoom. */
export const scaleIn: Variants = {
  hidden:  { opacity: 0, scale: 0.92 },
  visible: { opacity: 1, scale: 1, transition: transitions.slow },
};

/** Slide in from the left. */
export const slideInLeft: Variants = {
  hidden:  { opacity: 0, x: -40 },
  visible: { opacity: 1, x: 0, transition: transitions.slow },
};

/** Slide in from the right. */
export const slideInRight: Variants = {
  hidden:  { opacity: 0, x: 40 },
  visible: { opacity: 1, x: 0, transition: transitions.slow },
};

/** Word-by-word reveal (used for hero headline). */
export const wordReveal: Variants = {
  hidden:  { opacity: 0, y: 16, filter: "blur(8px)" },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.7, ease: EASE_OUT_EXPO },
  },
};

/** Hover lift for interactive cards. */
export const cardHover = {
  rest:  { y: 0, scale: 1 },
  hover: { y: -4, scale: 1.015, transition: transitions.fast },
} as const;

/* ──────────────────────────  Helpers  ───────────────────────── */

/** Split a string into per-word variant wrappers (for word reveals). */
export function splitWords(text: string): string[] {
  return text.split(/(\s+)/); // keep whitespace
}

/** Respect prefers-reduced-motion: if set, return no-op variants. */
export function reducedMotionVariants(
  enabled: boolean,
  fallback: Variants = { hidden: { opacity: 1 }, visible: { opacity: 1 } },
): Variants {
  return enabled ? fallback : fadeUp;
}
