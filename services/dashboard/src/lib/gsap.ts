/**
 * GSAP setup shared by every component that drives a gsap.to()/timeline
 * directly (framer-motion covers everything else — see @/lib/animations).
 * Centralized so ScrollTrigger is registered exactly once, not per-component.
 */
import gsap from "gsap/dist/gsap.js";
import { ScrollTrigger } from "gsap/dist/ScrollTrigger.js";

let registered = false;

export function ensureGsapRegistered(): void {
  if (registered) return;
  gsap.registerPlugin(ScrollTrigger);
  registered = true;
}

/** SSR-safe (static export prerenders on the server, where `window` is undefined). */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
