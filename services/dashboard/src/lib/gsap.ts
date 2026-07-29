/**
 * GSAP + ScrollTrigger helpers. Use these for scroll-driven
 * animations (parallax, scrub, pin) that are easier to express
 * in GSAP than Framer Motion.
 *
 * Framer Motion handles component-level enter/exit; GSAP handles
 * scroll-scrubbed timeline effects (the kind that look "expensive").
 */
"use client";

import gsap from "gsap/dist/gsap.js";
import { ScrollTrigger } from "gsap/dist/ScrollTrigger.js";

// Re-export the gsap default + ScrollTrigger named export
export { gsap, ScrollTrigger };
export default gsap;

let registered = false;

/** Register the ScrollTrigger plugin exactly once. Safe to call repeatedly. */
export function ensureGsapRegistered(): void {
  if (registered || typeof window === "undefined") return;
  gsap.registerPlugin(ScrollTrigger);
  registered = true;
}

/**
 * Scroll-driven counter (animates an integer from 0 → end as the
 * element scrolls into view). GSAP because we want a tween with a
 * precise scrub; Framer Motion counters are easier for non-scrub.
 */
export function animateCounter(
  el: HTMLElement | null,
  endValue: number,
  options: {
    duration?: number;
    decimals?: number;
    suffix?: string;
    prefix?: string;
    triggerStart?: string;
  } = {},
): gsap.core.Tween | null {
  if (!el) return null;
  ensureGsapRegistered();
  const { duration = 2, decimals = 0, suffix = "", prefix = "", triggerStart = "top 80%" } = options;
  const obj = { v: 0 };
  return gsap.to(obj, {
    v: endValue,
    duration,
    ease: "power2.out",
    scrollTrigger: {
      trigger: el,
      start: triggerStart,
      once: true,
    },
    onUpdate: () => {
      el.textContent = `${prefix}${obj.v.toFixed(decimals)}${suffix}`;
    },
  });
}

/**
 * Parallax: a wrapper that moves at a different rate than the
 * page during scroll. `speed` is the relative speed (negative =
 * opposite direction, e.g. -0.2 for slow upward drift).
 */
export function parallax(
  el: HTMLElement | null,
  speed: number = -0.2,
): gsap.core.Tween | null {
  if (!el) return null;
  ensureGsapRegistered();
  return gsap.to(el, {
    yPercent: speed * 100,
    ease: "none",
    scrollTrigger: {
      trigger: el,
      start: "top bottom",
      end: "bottom top",
      scrub: true,
    },
  });
}

/**
 * Pin a section while its children animate in (the "scrubbed
 * storytelling" effect). Use for hero sections where you want
 * the content to reveal as the user scrolls past.
 */
export function pinnedSection(
  trigger: HTMLElement,
  onPin?: (self: ScrollTrigger) => void,
): void {
  ensureGsapRegistered();
  ScrollTrigger.create({
    trigger,
    start: "top top",
    end: "+=80%",
    pin: true,
    pinSpacing: true,
    onUpdate: onPin,
  });
}

/** Refresh ScrollTrigger — call after dynamic content mounts. */
export function refreshScrollTrigger(): void {
  if (typeof window === "undefined") return;
  ensureGsapRegistered();
  ScrollTrigger.refresh();
}

/** Kill all ScrollTriggers. Call on route change to avoid memory leaks. */
export function killAllScrollTriggers(): void {
  if (typeof window === "undefined") return;
  ensureGsapRegistered();
  ScrollTrigger.getAll().forEach((t) => t.kill());
}

/**
 * Reduced-motion guard. Returns true if the user has set their
 * system preference to reduce motion; call this before kicking
 * off any GSAP tween to skip the animation.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
