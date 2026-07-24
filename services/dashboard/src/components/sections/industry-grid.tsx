/**
 * IndustryGrid — the 5-card industry grid for /solutions.
 * Each card has a photo background, overlay title, body, and "Learn more" link.
 */
"use client";

import type { ReactNode } from "react";
import Image from "next/image";
import { m } from "framer-motion";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { cardHover, fadeUp } from "@/lib/animations";

export interface Industry {
  title: string;
  body: string;
  href: string;
  image: string;
  alt: string;
}

export interface IndustryGridProps {
  badge?: string;
  heading?: ReactNode;
  subtitle?: string;
  items: Industry[];
  className?: string;
  bottomCta?: { label: string; href: string };
}

export function IndustryGrid({
  badge,
  heading,
  subtitle,
  items,
  className,
  bottomCta,
}: IndustryGridProps) {
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
            {subtitle && (
              <MotionItem variant="fadeUp">
                <p className="mt-3 text-white/60">{subtitle}</p>
              </MotionItem>
            )}
          </StaggerContainer>
        )}

        <StaggerContainer
          className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-5"
          staggerDelay={0.08}
        >
          {items.map((item) => (
            <MotionItem
              key={item.title}
              variant="fadeUp"
              className="group relative overflow-hidden rounded-2xl border border-white/10"
            >
              <m.div
                variants={cardHover}
                initial="rest"
                whileHover="hover"
                animate="rest"
                className="relative h-72 overflow-hidden"
              >
                <Image
                  src={item.image}
                  alt={item.alt}
                  width={500}
                  height={500}
                  loading="lazy"
                  className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                />
                <div
                  className="absolute inset-0"
                  style={{
                    background:
                      "linear-gradient(180deg, rgba(5,10,8,0.1) 0%, rgba(5,10,8,0.6) 50%, rgba(5,10,8,0.95) 100%)",
                  }}
                />
                <div className="absolute inset-0 flex flex-col justify-end p-5">
                  <div className="mb-3 grid h-9 w-9 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
                    <LeafIcon />
                  </div>
                  <h3 className="text-base font-semibold text-white">{item.title}</h3>
                  <p className="mt-1 text-xs leading-relaxed text-white/70">{item.body}</p>
                  <a
                    href={item.href}
                    className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-lime-300 transition-colors hover:text-lime-200"
                  >
                    Learn more <ArrowRight />
                  </a>
                </div>
              </m.div>
            </MotionItem>
          ))}
        </StaggerContainer>

        {bottomCta && (
          <MotionItem
            variant="fadeUp"
            className="mt-8 flex flex-col items-center justify-between gap-4 rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-6 md:flex-row"
          >
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
                <LeafIcon />
              </span>
              <div>
                <p className="text-sm font-semibold text-white">Don&apos;t see your industry?</p>
                <p className="text-xs text-white/60">EcoLens is flexible and adaptable to your unique needs.</p>
              </div>
            </div>
            <a
              href={bottomCta.href}
              className="inline-flex items-center gap-2 rounded-full border border-emerald-400/40 bg-emerald-400/5 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-400/10"
            >
              {bottomCta.label} <ArrowRight />
            </a>
          </MotionItem>
        )}
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

function LeafIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" />
    </svg>
  );
}

function ArrowRight() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path
        d="M2 6h7m0 0L6 3m3 3L6 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
