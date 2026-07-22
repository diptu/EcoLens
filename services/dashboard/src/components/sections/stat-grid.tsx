/**
 * StatGrid — the 4-stat grid with GSAP counter animation.
 * Used on /resources sidebar and /solutions real-impact section.
 */
"use client";

import { m } from "framer-motion";

import { MotionCounter, formatCompact, formatThousands } from "@/components/motion/motion-counter";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { cardHover } from "@/lib/animations";

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
  className?: string;
  /** Optional dark background container (default uses subtle border). */
  variant?: "default" | "cards" | "sidebar";
}

export function StatGrid({ stats, className, variant = "default" }: StatGridProps) {
  if (variant === "sidebar") {
    return (
      <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-6">
        <h3 className="text-lg font-semibold text-white">Turning Knowledge into Impact</h3>
        <StaggerContainer
          className="mt-6 space-y-5"
          staggerDelay={0.08}
        >
          {stats.map((stat) => (
            <MotionItem key={stat.label} variant="fadeUp" className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-md border border-emerald-400/20 bg-emerald-400/10 text-emerald-300">
                {stat.icon}
              </span>
              <div>
                <p className="text-2xl font-bold text-lime-300">
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

  if (variant === "cards") {
    return (
      <StaggerContainer
        className={className ?? "grid grid-cols-2 gap-4 md:grid-cols-4"}
        staggerDelay={0.1}
      >
        {stats.map((stat) => (
          <MotionItem
            key={stat.label}
            variant="fadeUp"
            className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 text-center"
          >
            <m.div
              variants={cardHover}
              initial="rest"
              whileHover="hover"
              animate="rest"
              className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-emerald-400/10 text-emerald-300"
            >
              {stat.icon}
            </m.div>
            <p className="text-3xl font-bold text-lime-300 md:text-4xl">
              <MotionCounter
                value={stat.value}
                prefix={stat.prefix}
                suffix={stat.suffix}
                decimals={stat.decimals}
                format={stat.format}
              />
            </p>
            <p className="mt-1 text-sm text-white/60">{stat.label}</p>
          </MotionItem>
        ))}
      </StaggerContainer>
    );
  }

  // default — bare list, no card wrapper
  return (
    <StaggerContainer className={className ?? "grid grid-cols-2 gap-6 md:grid-cols-4"} staggerDelay={0.1}>
      {stats.map((stat) => (
        <MotionItem key={stat.label} variant="fadeUp" className="text-center">
          <p className="text-3xl font-bold text-lime-300 md:text-4xl">
            <MotionCounter
              value={stat.value}
              prefix={stat.prefix}
              suffix={stat.suffix}
              decimals={stat.decimals}
              format={stat.format}
            />
          </p>
          <p className="mt-1 text-sm text-white/60">{stat.label}</p>
        </MotionItem>
      ))}
    </StaggerContainer>
  );
}

export { formatThousands, formatCompact };
