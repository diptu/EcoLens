"use client";

/**
 * Client wrapper that re-renders only the plan cards when the
 * monthly/annually toggle changes. Server-renders the static
 * structure + data on first paint, then takes over the price
 * updates.
 */
import { useState } from "react";
import { Check } from "lucide-react";

import { BillingToggle, useDefaultBillingPeriod, type BillingPeriod } from "@/components/pricing/billing-toggle";
import { cn } from "@/lib/utils";
import { PRICING_PLANS } from "@/lib/data";
import { Users, TrendingUp, Briefcase, Building2 } from "lucide-react";

const ICON_MAP = {
  users:        Users,
  "trending-up": TrendingUp,
  briefcase:    Briefcase,
  building:     Building2,
} as const;

function PlanCard({
  plan,
  period,
}: {
  plan: typeof PRICING_PLANS[number];
  period: BillingPeriod;
}) {
  const Icon = ICON_MAP[plan.icon as keyof typeof ICON_MAP] ?? Users;
  const showPrice = plan.price[period] !== null;
  return (
    <div
      className={cn(
        "relative flex flex-col rounded-2xl border p-6 transition-colors",
        plan.highlighted
          ? "border-emerald-400/40 bg-emerald-400/[0.02] shadow-[0_0_0_1px_rgba(132,204,22,0.2)]"
          : "border-white/10 bg-white/[0.02]"
      )}
    >
      {plan.highlighted && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-emerald-400 px-3 py-0.5 text-[10px] font-bold uppercase tracking-wider text-black">
          Most Popular
        </span>
      )}
      <span
        className={cn(
          "grid h-10 w-10 place-items-center rounded-full",
          plan.highlighted ? "bg-emerald-400/15" : "bg-white/[0.04]"
        )}
      >
        <Icon className="h-5 w-5 text-emerald-300" />
      </span>
      <h3 className="mt-4 text-lg font-bold text-white">{plan.name}</h3>
      <p className="mt-1 min-h-[2.5rem] text-xs leading-relaxed text-white/60">
        {plan.description}
      </p>
      <div className="mt-5 min-h-[3.5rem]">
        {showPrice ? (
          <>
            <div className="flex items-baseline gap-1">
              <span className="text-4xl font-extrabold text-white">
                ${plan.price[period]}
              </span>
              <span className="text-sm text-white/50">/month</span>
            </div>
            <p className="mt-1 text-[10px] uppercase tracking-wider text-white/40">
              Billed annually
            </p>
          </>
        ) : (
          <>
            <div className="text-4xl font-extrabold text-white">
              {plan.customLabel ?? "Custom"}
            </div>
            <p className="mt-1 text-[10px] uppercase tracking-wider text-white/40">
              Billed annually
            </p>
          </>
        )}
      </div>
      <ul className="mt-5 space-y-2 text-sm text-white/75">
        {plan.features.map((feat) => (
          <li key={feat} className="flex items-start gap-2">
            <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" />
            <span>{feat}</span>
          </li>
        ))}
      </ul>
      <a
        href={plan.cta.href}
        className={cn(
          "mt-6 inline-flex w-full items-center justify-center rounded-md px-4 py-2.5 text-sm font-semibold transition-colors",
          plan.highlighted
            ? "bg-lime-300 text-black hover:bg-lime-200"
            : "border border-emerald-400/30 bg-emerald-400/5 text-emerald-300 hover:bg-emerald-400/10"
        )}
      >
        {plan.cta.label}
      </a>
    </div>
  );
}

export function PlansGrid() {
  const [period, setPeriod] = useDefaultBillingPeriod();
  return (
    <>
      <div className="mt-8 flex justify-center">
        <BillingToggle value={period} onChange={setPeriod} />
      </div>
      <div className="mx-auto mt-10 grid max-w-6xl grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {PRICING_PLANS.map((plan) => (
          <PlanCard key={plan.id} plan={plan} period={period} />
        ))}
      </div>
    </>
  );
}
