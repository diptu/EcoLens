/**
 * 5-feature row (Easy Data Ingestion, AI-Powered Calculation, etc.).
 * Each cell is a small icon + title + body. Cards animate in on
 * scroll via the StaggerContainer, and lift on hover.
 */
"use client";

import { m } from "framer-motion";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { cardHover, fadeUp } from "@/lib/animations";

interface Feature {
  title: string;
  body: string;
  icon: React.ReactNode;
}

const FEATURES: Feature[] = [
  {
    title: "Easy Data Ingestion",
    body: "Connect your data sources in minutes. We handle the complexity.",
    icon: <CloudIcon />,
  },
  {
    title: "AI-Powered Calculation",
    body: "Industry-leading models ensure accuracy and transparency.",
    icon: <CpuIcon />,
  },
  {
    title: "Actionable Insights",
    body: "Understand your footprint and discover reduction opportunities.",
    icon: <ChartIcon />,
  },
  {
    title: "Report & Comply",
    body: "Generate audit-ready reports aligned with global standards.",
    icon: <DocIcon />,
  },
  {
    title: "Drive Impact",
    body: "Set goals, track progress, and communicate your impact.",
    icon: <LeafIcon />,
  },
];

export function FeaturesRow() {
  return (
    <section className="border-t border-white/5 py-16 md:py-20">
      <StaggerContainer
        className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-6 sm:grid-cols-2 lg:grid-cols-5"
        stagger={true}
        staggerDelay={0.08}
      >
        {FEATURES.map((feature) => (
          <MotionItem
            key={feature.title}
            variant="fadeUp"
            className="group flex flex-col items-center text-center"
          >
            <m.div
              variants={cardHover}
              initial="rest"
              whileHover="hover"
              animate="rest"
              className="flex w-full flex-col items-center rounded-2xl border border-transparent p-4 transition-colors hover:border-white/10 hover:bg-white/[0.02]"
            >
              <m.div
                whileHover={{ scale: 1.1, rotate: 4 }}
                transition={{ type: "spring", stiffness: 300, damping: 15 }}
                className="grid h-12 w-12 place-items-center rounded-xl border border-emerald-400/20 bg-emerald-400/5 text-emerald-300"
              >
                {feature.icon}
              </m.div>
              <h3 className="mt-4 text-base font-semibold text-white">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/60">{feature.body}</p>
            </m.div>
          </MotionItem>
        ))}
      </StaggerContainer>
    </section>
  );
}

/* ─────────────────  Icons  ───────────────── */

function CloudIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M7 18a4 4 0 010-8 6 6 0 0111.5 1.5A4 4 0 0118 18H7z" strokeLinejoin="round" />
    </svg>
  );
}
function CpuIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M10 10h4v4h-4z" />
      <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" strokeLinecap="round" />
    </svg>
  );
}
function ChartIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M3 21h18M6 17V9M11 17V5M16 17v-6M21 17v-3" strokeLinecap="round" />
    </svg>
  );
}
function DocIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" strokeLinejoin="round" />
      <path d="M14 3v5h5M9 13h6M9 17h4" strokeLinecap="round" />
    </svg>
  );
}
function LeafIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
      <path d="M19 5C9 7 6 14 4 19l1.5.5.8-2c.6-.1 1.2 0 1.7 0 4.5 0 8-3.5 8-9V5h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L19 5z" />
    </svg>
  );
}
