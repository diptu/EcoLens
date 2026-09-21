/**
 * StatGrid — a bordered stat panel with GSAP counter animation.
 * Used on /resources and /blog.
 */
"use client";

import { MotionCounter } from "@/components/motion/motion-counter";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";

export interface StatItem {
  value: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  label: string;
  format?: (n: number) => string;
  icon: React.ReactNode;
}

export interface StatGridProps {
  stats: StatItem[];
  /** Panel heading. */
  heading?: string;
}

export function StatGrid({ stats, heading = "Turning Knowledge into Impact" }: StatGridProps) {
  return (
    <div className="rounded-2xl border border-emerald-200/20 bg-emerald-200/5 p-6">
      <h3 className="text-lg font-semibold text-white">{heading}</h3>
      <StaggerContainer className="mt-6 space-y-5" staggerDelay={0.08}>
        {stats.map((stat) => (
          <MotionItem key={stat.label} variant="fadeUp" className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-md border border-emerald-200/20 bg-emerald-200/10 text-emerald-100">
              {stat.icon}
            </span>
            <div>
              <p className="text-2xl font-bold text-lime-100">
                <MotionCounter
                  value={stat.value}
                  prefix={stat.prefix}
                  suffix={stat.suffix}
                  decimals={stat.decimals}
                  format={stat.format}
                />
              </p>
              <p className="text-xs text-white/70">{stat.label}</p>
            </div>
          </MotionItem>
        ))}
      </StaggerContainer>
    </div>
  );
}
