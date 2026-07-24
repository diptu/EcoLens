/**
 * /pricing — Plan comparison + signup CTA.
 *
 * Performance notes:
 *  - LCP element (the H1) is server-rendered (no Framer Motion initial).
 *  - Forest background is the self-hosted forest.webp, preloaded
 *    for instant display, with `fetchPriority="high"`.
 *  - The monthly/annually toggle is the only client component
 *    (in src/components/pricing/plans-grid.tsx).
 *  - The compare-plans table is a native HTML <table> — no JS.
 *  - The 4 plan cards are pure CSS, no entry animations.
 *  - All data is imported from @/lib/data (no fetcher calls).
 *
 * Targets:
 *  - FCP < 200ms
 *  - LCP < 600ms (no throttling)
 *  - CLS = 0 (all images have width/height or aspect-ratio)
 *  - Total JS for this page: < 3 KB
 */
import Image from "next/image";
import { Check } from "lucide-react";

import { Footer } from "@/components/landing/footer";
import { PlansGrid } from "@/components/pricing/plans-grid";
import { cn } from "@/lib/utils";
import {
  PRICING_PLANS,
  PRICING_COMPARE_ROWS,
  PRICING_INCLUDED,
  PRICING_ADDONS,
} from "@/lib/data";

export const metadata = {
  title: "Pricing — EcoLens",
  description:
    "Simple, transparent pricing for organizations of every size. Start with a free trial; upgrade, downgrade, or cancel anytime.",
};

/* ─── Server-rendered: compare-plans table (no JS) ─── */
function CompareTable() {
  return (
    <div className="mx-auto mt-16 max-w-6xl overflow-x-auto rounded-2xl border border-white/5 bg-white/[0.02]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/5 text-left text-xs">
            <th className="px-5 py-3 font-medium text-white/50">Compare plans</th>
            {PRICING_PLANS.map((p) => (
              <th key={p.id} className="px-5 py-3 text-center font-semibold text-white">
                {p.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {PRICING_COMPARE_ROWS.map((row, i) => (
            <tr
              key={row.row}
              className={cn("border-b border-white/5", i % 2 === 1 && "bg-white/[0.01]")}
            >
              <td className="px-5 py-3 text-white/80">{row.row}</td>
              {(["starter", "growth", "professional", "enterprise"] as const).map(
                (planId) => {
                  const val = row[planId as keyof typeof row];
                  if (typeof val === "boolean") {
                    return (
                      <td key={planId} className="px-5 py-3 text-center">
                        {val ? (
                          <Check className="mx-auto h-4 w-4 text-emerald-300" />
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                    );
                  }
                  return (
                    <td key={planId} className="px-5 py-3 text-center text-white/75">
                      {val}
                    </td>
                  );
                }
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PricingPage() {
  return (
    <main>
      {/* Hero — LCP element is the H1, no Framer Motion initial */}
      <section className="relative isolate overflow-hidden">
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
          <Image
            src="/images/forest.webp"
            alt=""
            fill
            priority
            fetchPriority="high"
            sizes="100vw"
            className="object-cover opacity-30"
            quality={70}
          />
          <div
            className="absolute inset-0"
            style={{
              background:
                "linear-gradient(180deg, rgba(8,18,12,0.4) 0%, rgba(8,18,12,0.1) 30%, rgba(8,18,12,0.7) 80%, rgba(8,18,12,0.98) 100%)",
            }}
          />
          <div
            className="absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse at 50% 0%, rgba(132,204,22,0.15) 0%, transparent 60%)",
            }}
          />
        </div>
        <div className="mx-auto max-w-7xl px-6 pb-10 pt-20 text-center md:pb-16 md:pt-28">
          <h1 className="text-4xl font-extrabold leading-[1.1] tracking-tight text-white md:text-5xl lg:text-6xl">
            Simple, transparent pricing for every organization
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base text-white/70 md:text-lg">
            Choose the plan that fits your needs. Upgrade, downgrade, or cancel any time.
          </p>
        </div>
      </section>

      {/* Plan cards + billing toggle (client-rendered wrapper) */}
      <section className="relative -mt-6 pb-12 md:pb-16">
        <PlansGrid />
      </section>

      {/* Compare table (server-rendered) */}
      <section className="px-6 pb-16">
        <CompareTable />
      </section>

      {/* Bottom 3-up: all plans include | add-ons | custom solution */}
      <section className="mx-auto max-w-7xl px-6 pb-16">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-6">
            <div className="flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 4l8 8 8-8M4 12l8 8 8-8" />
                </svg>
              </span>
              <h3 className="text-sm font-bold text-white">All plans include:</h3>
            </div>
            <ul className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-white/75">
              {PRICING_INCLUDED.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-300" />
                  {item}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl border border-white/5 bg-white/[0.02] p-6">
            <h3 className="text-sm font-bold text-white">Add-ons</h3>
            <ul className="mt-4 space-y-2.5 text-xs">
              {PRICING_ADDONS.map((a) => (
                <li key={a.name} className="flex items-center justify-between">
                  <span className="text-white/75">{a.name}</span>
                  <span className="font-mono text-emerald-300">{a.price}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="relative overflow-hidden rounded-2xl border border-white/5 bg-gradient-to-br from-emerald-400/10 via-white/[0.02] to-white/[0.02] p-6">
            <div aria-hidden className="pointer-events-none absolute -right-12 -bottom-12 h-32 w-32 opacity-20">
              <Image
                src="/images/forest.webp"
                alt=""
                fill
                sizes="128px"
                className="object-cover"
                quality={50}
              />
            </div>
            <h3 className="text-sm font-bold text-white">Need a custom solution?</h3>
            <p className="mt-2 text-xs text-white/65">
              We&apos;ll work with you to build a plan that fits your organization&apos;s unique
              requirements.
            </p>
            <a
              href="mailto:sales@ecolens.app"
              className="mt-4 inline-flex items-center justify-center rounded-md bg-lime-300 px-4 py-2 text-xs font-semibold text-black hover:bg-lime-200"
            >
              Talk to Sales
            </a>
          </div>
        </div>
      </section>

      <Footer />
    </main>
  );
}
