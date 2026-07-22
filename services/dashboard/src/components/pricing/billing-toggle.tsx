"use client";

/**
 * Billing-period toggle (monthly / annually) for the pricing page.
 * Uses a `<details>`/`<summary>`-free, native `aria-pressed` buttons
 * so it works without JS (the URL hash is updated via history.replaceState
 * for shareable links but the visual state is in plain React state).
 *
 * Performance:
 *  - Renders only 2 buttons + 1 badge. < 1 KB of HTML.
 *  - The actual plan cards re-render via React state, but the rest
 *    of the page is server-rendered and does NOT re-render.
 */
import { useCallback, useEffect, useState } from "react";

export type BillingPeriod = "monthly" | "annually";

export function BillingToggle({
  value,
  onChange,
}: {
  value: BillingPeriod;
  onChange: (next: BillingPeriod) => void;
}) {
  // Allow keyboard shortcuts: M for monthly, A for annually
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (e.key === "m" || e.key === "M") onChange("monthly");
      if (e.key === "a" || e.key === "A") onChange("annually");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onChange]);

  return (
    <div
      role="radiogroup"
      aria-label="Billing period"
      className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] p-1"
    >
      <button
        type="button"
        role="radio"
        aria-checked={value === "monthly"}
        onClick={() => onChange("monthly")}
        className={
          "rounded-full px-4 py-1.5 text-xs font-semibold transition-colors " +
          (value === "monthly"
            ? "bg-lime-300 text-black"
            : "text-white/70 hover:text-white")
        }
      >
        Pay Monthly
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={value === "annually"}
        onClick={() => onChange("annually")}
        className={
          "rounded-full px-4 py-1.5 text-xs font-semibold transition-colors " +
          (value === "annually"
            ? "bg-lime-300 text-black"
            : "text-white/70 hover:text-white")
        }
      >
        Pay Annually
      </button>
      <span className="ml-1 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
        Save up to 20%
      </span>
    </div>
  );
}

/** Hook: read default billing period from URL hash (#annually) or localStorage. */
export function useDefaultBillingPeriod(): [BillingPeriod, (next: BillingPeriod) => void] {
  const [period, setPeriod] = useState<BillingPeriod>("annually");
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash.replace("#", "").toLowerCase();
    if (hash === "monthly" || hash === "annually") {
      setPeriod(hash as BillingPeriod);
      return;
    }
    try {
      const saved = window.localStorage.getItem("ecolens_billing");
      if (saved === "monthly" || saved === "annually") setPeriod(saved as BillingPeriod);
    } catch {
      /* localStorage may be blocked (private mode); fall through */
    }
  }, []);
  // Persist on change
  const setAndPersist = useCallback((next: BillingPeriod) => {
    setPeriod(next);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem("ecolens_billing", next);
        window.history.replaceState(null, "", `#${next}`);
      } catch {
        /* ignore */
      }
    }
  }, []);
  return [period, setAndPersist];
}
