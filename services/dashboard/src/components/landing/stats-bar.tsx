/**
 * Stats bar — 4 KPIs that animate in with the GSAP counter
 * (0 → value as the section enters the viewport).
 */
"use client";

import { m } from "framer-motion";

import { MotionCounter, formatCompact, formatThousands } from "@/components/motion/motion-counter";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp } from "@/lib/animations";

interface Stat {
  value: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  label: string;
  format?: (n: number) => string;
  icon: React.ReactNode;
}

const STATS: Stat[] = [
  {
    value: 1250,
    suffix: "+",
    format: formatThousands,
    label: "Organizations",
    icon: <BuildingIcon />,
  },
  {
    value: 2.4,
    suffix: "M+",
    decimals: 1,
    label: "tCO₂e Measured",
    icon: <LeafIcon />,
  },
  {
    value: 28,
    suffix: "%",
    label: "Avg. Emission Reduced",
    icon: <ChartIcon />,
  },
  {
    value: 75,
    suffix: "+",
    format: formatThousands,
    label: "Countries",
    icon: <GlobeIcon />,
  },
];

export function StatsBar() {
  return (
    <StaggerContainer className="border-y border-white/5 bg-white/[0.02] py-10">
      <div className="mx-auto grid max-w-7xl grid-cols-2 gap-y-8 px-6 md:grid-cols-4 md:gap-y-0">
        {STATS.map((stat, i) => (
          <MotionItem
            key={stat.label}
            variant="fadeUp"
            className={
              "flex flex-col items-center gap-2 text-center " +
              (i < STATS.length - 1 ? "md:border-r md:border-white/5" : "")
            }
          >
            <div className="flex items-center gap-3">
              <m.div
                whileHover={{ rotate: 8, scale: 1.05 }}
                transition={{ type: "spring", stiffness: 300, damping: 15 }}
                className="grid h-9 w-9 place-items-center rounded-full bg-emerald-400/10 text-emerald-300"
              >
                {stat.icon}
              </m.div>
              <div className="text-3xl font-bold text-lime-300 md:text-4xl">
                <MotionCounter
                  value={stat.value}
                  prefix={stat.prefix}
                  suffix={stat.suffix}
                  decimals={stat.decimals}
                  format={stat.format}
                />
              </div>
            </div>
            <p className="text-sm text-white/60">{stat.label}</p>
          </MotionItem>
        ))}
      </div>
    </StaggerContainer>
  );
}

/* ─────────────────  Icons  ───────────────── */

function BuildingIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4">
      <rect x="3" y="2" width="12" height="14" rx="1" />
      <path d="M6 6h2M6 9h2M6 12h2M10 6h2M10 9h2M10 12h2" strokeLinecap="round" />
    </svg>
  );
}

function LeafIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
      <path d="M14 4c-7 2-9 8-10.5 12l1.5.5.8-1.8c.5-.1 1 .0 1.5 0 4 0 7.2-3.2 7.2-8V4h-.4c-.2 0-.4.2-.4.4 0 .2 0 .3.1.4L14 4z" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M3 14l4-4 3 3 5-7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M15 6h-2M15 6v2" strokeLinecap="round" />
    </svg>
  );
}

function GlobeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4">
      <circle cx="9" cy="9" r="6.5" />
      <path d="M2.5 9h13M9 2.5c2 2 2 11 0 13M9 2.5c-2 2-2 11 0 13" />
    </svg>
  );
}
