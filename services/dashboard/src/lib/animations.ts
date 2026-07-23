/**
 * Shared Framer Motion variants. Every animated section/item in the app
 * composes these instead of hand-rolling its own transition config, so
 * timing/easing stays consistent site-wide (see components/motion/*).
 */
import type { Variants } from "framer-motion";

const EASE = [0.16, 1, 0.3, 1] as const;

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.6, ease: EASE } },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.95 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: EASE } },
};

export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -32 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.6, ease: EASE } },
};

export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 32 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.6, ease: EASE } },
};

export const staggerContainer: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.08, delayChildren: 0.1 },
  },
};

/** Per-word reveal — apply to each `m.span` inside a `staggerContainer`. */
export const wordReveal: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE } },
};

/** `variants={cardHover}` + `initial="rest"` `whileHover="hover"` `animate="rest"`. */
export const cardHover: Variants = {
  rest: { y: 0, scale: 1 },
  hover: { y: -4, scale: 1.015, transition: { duration: 0.25, ease: EASE } },
};

/** `prefers-reduced-motion` fallback: same hidden/visible keys, no motion. */
export function reducedMotionVariants(reduced: boolean): Variants {
  if (!reduced) return fadeUp;
  return {
    hidden: { opacity: 1 },
    visible: { opacity: 1 },
  };
}
