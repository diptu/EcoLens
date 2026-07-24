/**
 * ResourceCard — featured resource card with thumbnail image and metadata pill.
 * Used on /resources "Featured Resources" section.
 */
"use client";

import Image from "next/image";
import { m } from "framer-motion";
import type { ReactNode } from "react";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { cardHover, fadeUp } from "@/lib/animations";

export interface ResourceItem {
  type: string;          // "GUIDE" | "TEMPLATE" | "REPORT" | "WEBINAR" | "CASE STUDY"
  title: string;
  body: string;
  meta: string;          // "15 min read"
  level: string;         // "Beginner" | "Intermediate" | "Advanced"
  image: string;
  alt: string;
  href: string;
}

export interface ResourceCardProps {
  items: ResourceItem[];
  className?: string;
}

export function ResourceCard({ items, className }: ResourceCardProps) {
  return (
    <StaggerContainer
      className={className ?? "grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-5"}
      staggerDelay={0.08}
    >
      {items.map((r) => (
        <MotionItem
          key={r.title}
          variant="fadeUp"
          className="group overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] transition-colors hover:border-emerald-400/30"
        >
          <m.div
            variants={cardHover}
            initial="rest"
            whileHover="hover"
            animate="rest"
            className="relative h-40 overflow-hidden"
          >
            <Image
              src={r.image}
              alt={r.alt}
              width={500}
              height={300}
              loading="lazy"
              className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
            />
            <span className="absolute left-3 top-3 rounded-md bg-emerald-400/90 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-black">
              {r.type}
            </span>
            <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
          </m.div>
          <div className="p-4">
            <h3 className="text-sm font-semibold text-white">{r.title}</h3>
            <p className="mt-2 line-clamp-2 text-xs text-white/60">{r.body}</p>
            <div className="mt-3 flex items-center justify-between text-[11px]">
              <span className="inline-flex items-center gap-1 text-white/50">
                <ClockIcon /> {r.meta}
              </span>
              <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-emerald-300">
                {r.level}
              </span>
            </div>
          </div>
        </MotionItem>
      ))}
    </StaggerContainer>
  );
}

function ClockIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6 3.5V6L7.5 7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

export { fadeUp };
