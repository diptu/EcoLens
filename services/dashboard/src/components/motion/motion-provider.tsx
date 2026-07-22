/**
 * LazyMotion + domAnimation provider.
 *
 * LazyMotion dramatically reduces Framer Motion's bundle size by only
 * loading the animation features we actually use. Without it, Framer
 * ships ~50KB of features; with it, we ship ~5KB.
 *
 * We use `domAnimation` (not `domMax`) because we only animate
 * CSS-compatible properties (transform, opacity). Layout-measure
 * features (used for FLIP-style animations) are excluded.
 */
"use client";

import { LazyMotion, domAnimation, MotionConfig } from "framer-motion";
import type { ReactNode } from "react";

export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}
