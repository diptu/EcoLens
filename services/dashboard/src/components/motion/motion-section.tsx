/**
 * Reusable motion primitives. Every section in the app should
 * compose these instead of writing its own m.div.
 */
"use client";

import { m, useReducedMotion, type HTMLMotionProps } from "framer-motion";
import { forwardRef, type ReactNode } from "react";

import {
  fadeUp,
  fadeIn,
  scaleIn,
  slideInLeft,
  slideInRight,
  staggerContainer,
  reducedMotionVariants,
} from "@/lib/animations";

/* ─────────────────────────  Types  ───────────────────────── */

type Direction = "up" | "down" | "left" | "right" | "none";
type ViewportAmount = 0.1 | 0.25 | 0.5 | 0.75 | 1;

export interface MotionSectionProps extends Omit<HTMLMotionProps<"section">, "variants"> {
  /** Which entrance animation to use. */
  variant?: "fadeUp" | "fadeIn" | "scaleIn" | "slideInLeft" | "slideInRight";
  /** When true, this section's children stagger in. */
  stagger?: boolean;
  /** Stagger delay between children (seconds). */
  staggerDelay?: number;
  /** Whether to animate only on first viewport entry. */
  once?: boolean;
  /** Fraction of section that must be in view before animating. */
  viewportAmount?: ViewportAmount;
  /** Override the direction (currently informational; variant decides). */
  direction?: Direction;
  children: ReactNode;
}

const variantMap = {
  fadeUp,
  fadeIn,
  scaleIn,
  slideInLeft,
  slideInRight,
};

/* ─────────────────  StaggerContainer wrapper  ───────────────── */

export const StaggerContainer = forwardRef<HTMLElement, MotionSectionProps>(
  function StaggerContainer(
    { children, className, viewportAmount = 0.2, once = true, ...rest },
    ref,
  ) {
    const reduceMotion = useReducedMotion();
    return (
      <m.section
        ref={ref}
        className={className}
        variants={reduceMotion ? reducedMotionVariants(true) : staggerContainer}
        initial="hidden"
        whileInView="visible"
        viewport={{ once, amount: viewportAmount }}
        {...rest}
      >
        {children}
      </m.section>
    );
  },
);

/* ─────────────────  AnimatedSection (single child)  ───────────────── */

export const AnimatedSection = forwardRef<HTMLElement, MotionSectionProps>(
  function AnimatedSection(
    {
      children,
      className,
      variant = "fadeUp",
      stagger = false,
      staggerDelay = 0.08,
      once = true,
      viewportAmount = 0.3,
      ...rest
    },
    ref,
  ) {
    const reduceMotion = useReducedMotion();
    const variants = reduceMotion
      ? reducedMotionVariants(true)
      : stagger
        ? {
            ...staggerContainer,
            visible: {
              ...staggerContainer.visible,
              transition: {
                staggerChildren: staggerDelay,
                delayChildren: 0.1,
              },
            },
          }
        : variantMap[variant];

    return (
      <m.section
        ref={ref}
        className={className}
        variants={variants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once, amount: viewportAmount }}
        {...rest}
      >
        {children}
      </m.section>
    );
  },
);

/* ─────────────────  Item (used inside StaggerContainer)  ───────────────── */

export interface MotionItemProps extends HTMLMotionProps<"div"> {
  variant?: "fadeUp" | "fadeIn" | "scaleIn" | "slideInLeft" | "slideInRight";
}

export const MotionItem = forwardRef<HTMLDivElement, MotionItemProps>(
  function MotionItem({ children, className, variant = "fadeUp", ...rest }, ref) {
    const reduceMotion = useReducedMotion();
    const variants = reduceMotion ? reducedMotionVariants(true) : variantMap[variant];
    return (
      <m.div ref={ref} className={className} variants={variants} {...rest}>
        {children}
      </m.div>
    );
  },
);
