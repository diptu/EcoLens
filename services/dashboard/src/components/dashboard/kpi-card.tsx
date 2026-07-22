/**
 * KpiCard — large stat tile with label, value, unit, optional
 * sub-line and trend. Used in the row of 4–5 cards at the top
 * of most dashboard pages.
 */
import { ArrowDown, ArrowUp } from "lucide-react";

import { cn } from "@/lib/utils";

export interface KpiCardProps {
  icon?: React.ReactNode;
  label: string;
  value: string | number;
  unit?: string;
  sub?: string;
  trend?: { direction: "up" | "down" | "flat"; text: string; goodWhen?: "up" | "down" };
  suffix?: React.ReactNode;
  className?: string;
}

export function KpiCard({
  icon,
  label,
  value,
  unit,
  sub,
  trend,
  className,
}: KpiCardProps) {
  const trendGood =
    !trend ||
    (trend.direction === "flat") ||
    (trend.goodWhen && trend.direction === trend.goodWhen);
  const trendColor = trend
    ? trend.direction === "flat"
      ? "text-white/50"
      : trendGood
        ? "text-emerald-400"
        : "text-rose-400"
    : "text-white/50";

  return (
    <div className={cn("rounded-xl border border-white/5 bg-white/[0.02] p-5", className)}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-white/60">{label}</p>
        {icon && (
          <span className="grid h-7 w-7 place-items-center rounded-full bg-emerald-400/10 text-emerald-300">
            {icon}
          </span>
        )}
      </div>
      <div className="mt-3 flex items-baseline gap-1.5">
        <p className="text-2xl font-bold text-white md:text-3xl">{value}</p>
        {unit && <p className="text-sm text-white/50">{unit}</p>}
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-xs">
        {trend && (
          <span className={cn("flex items-center gap-1 font-medium", trendColor)}>
            {trend.direction === "up" && <ArrowUp className="h-3 w-3" />}
            {trend.direction === "down" && <ArrowDown className="h-3 w-3" />}
            {trend.text}
          </span>
        )}
        {sub && <span className="text-white/50">{sub}</span>}
      </div>
    </div>
  );
}
