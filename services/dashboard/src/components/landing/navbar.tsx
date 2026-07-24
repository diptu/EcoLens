/**
 * Top navigation bar.
 *
 * Performance: uses plain HTML + CSS for the initial entrance so
 * the navbar is visible in the SSR'd HTML (no `opacity: 0` trap).
 * Framer Motion (`m.X`) is used only for hover micro-interactions
 * and the mobile dropdown — features that don't need to fire on
 * first paint.
 *
 * Sticky + glass on scroll (state managed in useEffect for
 * the scroll listener; the visual style is a pure CSS class swap).
 */
"use client";

import { AnimatePresence, m } from "framer-motion";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { MotionButton } from "@/components/motion/motion-button";
import { cn } from "@/lib/utils";

const NAV_LINKS: Array<{ label: string; href: string; hasMenu?: boolean }> = [
  { label: "Product",   href: "/product",   hasMenu: true },
  { label: "Solutions", href: "/solutions", hasMenu: true },
  { label: "Pricing",   href: "/pricing" },
  { label: "Resources", href: "/resources", hasMenu: true },
  { label: "About",     href: "/about" },
];

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        // CSS-only entrance: no Framer Motion `initial/animate` so the
        // navbar is visible in the SSR'd HTML (no `opacity: 0` trap).
        "nav-enter sticky top-0 z-50 w-full transition-all duration-300",
        scrolled
          ? "border-b border-white/5 bg-[#050a08]/80 backdrop-blur-xl"
          : "bg-transparent",
      )}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2">
          <m.div
            whileHover={{ rotate: 12 }}
            transition={{ type: "spring", stiffness: 300, damping: 15 }}
            className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-emerald-400 to-lime-300"
          >
            <LeafIcon className="h-4 w-4 text-black" />
          </m.div>
          <span className="text-lg font-bold text-white">EcoLens</span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((link) => (
            <m.div
              key={link.href}
              whileHover="hover"
              initial="rest"
              animate="rest"
              className="relative"
            >
              <Link
                href={link.href}
                className="flex items-center gap-1 px-4 py-2 text-sm text-white/80 transition-colors hover:text-white"
              >
                {link.label}
                {link.hasMenu && (
                  <m.svg
                    variants={{ rest: { rotate: 0 }, hover: { rotate: 180 } }}
                    transition={{ duration: 0.2 }}
                    width="10"
                    height="10"
                    viewBox="0 0 10 10"
                    className="text-white/60"
                  >
                    <path d="M2 4l3 3 3-3" stroke="currentColor" strokeWidth="1.5" fill="none" />
                  </m.svg>
                )}
              </Link>
            </m.div>
          ))}
        </nav>

        {/* Desktop CTAs */}
        <div className="hidden items-center gap-3 md:flex">
          <Link
            href="/login"
            className="text-sm text-white/80 transition-colors hover:text-white"
          >
            Log in
          </Link>
          <MotionButton size="sm" iconAfter={<ArrowIcon />}>
            Get Started
          </MotionButton>
        </div>

        {/* Mobile toggle */}
        <button
          type="button"
          onClick={() => setMobileOpen((o) => !o)}
          className="grid h-10 w-10 place-items-center rounded-full border border-white/10 bg-white/5 md:hidden"
          aria-label="Toggle menu"
        >
          {mobileOpen ? <X className="h-4 w-4 text-white" /> : <Menu className="h-4 w-4 text-white" />}
        </button>
      </div>

      {/* Mobile dropdown */}
      <AnimatePresence>
        {mobileOpen && (
          <m.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden border-t border-white/5 bg-[#050a08]/95 md:hidden"
          >
            <div className="flex flex-col gap-1 px-6 py-4">
              {NAV_LINKS.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="rounded-md px-3 py-2 text-sm text-white/80 hover:bg-white/5 hover:text-white"
                  onClick={() => setMobileOpen(false)}
                >
                  {link.label}
                </Link>
              ))}
              <div className="mt-2 flex flex-col gap-2 border-t border-white/5 pt-3">
                <Link
                  href="/login"
                  className="rounded-md px-3 py-2 text-sm text-white/80"
                  onClick={() => setMobileOpen(false)}
                >
                  Log in
                </Link>
                <MotionButton size="sm" iconAfter={<ArrowIcon />}>
                  Get Started
                </MotionButton>
              </div>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </header>
  );
}

/* ─────────────────  Icons  ───────────────── */

function LeafIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path
        d="M3 6h6m0 0L6 3m3 3L6 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
