/**
 * StepFlow — the "From Data to Impact in N Steps" horizontal flow with
 * numbered cards and a dashed connector line. Used on /product (4 steps).
 */
"use client";

import { m } from "framer-motion";
import { type ReactNode } from "react";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp } from "@/lib/animations";

export interface Step {
  number: number;
  title: string;
  body: string;
  icon: ReactNode;
}

export interface StepFlowProps {
  badge?: string;
  heading: ReactNode;
  steps: Step[];
  className?: string;
}

export function StepFlow({ badge, heading, steps, className }: StepFlowProps) {
  return (
    <section className={className ?? "py-20 md:py-24"}>
      <div className="mx-auto max-w-7xl px-6">
        {(badge || heading) && (
          <StaggerContainer className="mx-auto mb-12 max-w-2xl text-center">
            {badge && (
              <MotionItem variant="fadeIn">
                <CenterBadge>{badge}</CenterBadge>
              </MotionItem>
            )}
            <MotionItem variant="fadeUp">
              <h2 className="mt-4 text-3xl font-bold leading-tight text-white md:text-4xl">
                {heading}
              </h2>
            </MotionItem>
          </StaggerContainer>
        )}

        <StaggerContainer
          className="relative grid grid-cols-1 gap-8 sm:grid-cols-2 md:grid-cols-4"
          staggerDelay={0.1}
        >
          {/* Dashed connector line — desktop only */}
          <div
            aria-hidden="true"
            className="absolute left-[12%] right-[12%] top-9 hidden h-px md:block"
            style={{
              backgroundImage:
                "repeating-linear-gradient(90deg, rgba(132,204,22,0.4) 0 6px, transparent 6px 12px)",
            }}
          />
          {steps.map((step) => (
            <MotionItem
              key={step.number}
              variant="fadeUp"
              className="relative flex flex-col items-center text-center"
            >
              <m.div
                whileHover={{ scale: 1.06, rotate: 4 }}
                transition={{ type: "spring", stiffness: 300, damping: 15 }}
                className="relative grid h-[72px] w-[72px] place-items-center rounded-full border border-emerald-400/30 bg-[#0a1410]"
              >
                <span className="text-2xl text-emerald-300">{step.icon}</span>
                <span className="absolute -top-1 -right-1 grid h-6 w-6 place-items-center rounded-full bg-lime-300 text-[10px] font-bold text-black">
                  {step.number}
                </span>
              </m.div>
              <h3 className="mt-4 text-base font-semibold text-white">
                {step.number}. {step.title}
              </h3>
              <p className="mt-1 max-w-[200px] text-sm text-white/60">{step.body}</p>
            </MotionItem>
          ))}
        </StaggerContainer>
      </div>
    </section>
  );
}

function CenterBadge({ children }: { children: React.ReactNode }) {
  return (
    <m.span
      variants={fadeUp}
      className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium tracking-wider text-emerald-300"
    >
      <span className="grid h-4 w-4 place-items-center rounded-full bg-emerald-400/20">
        <svg viewBox="0 0 8 8" fill="currentColor" className="h-2.5 w-2.5">
          <path d="M4 0L4.6 3.4L8 4L4.6 4.6L4 8L3.4 4.6L0 4L3.4 3.4Z" />
        </svg>
      </span>
      {String(children).toUpperCase()}
    </m.span>
  );
}
