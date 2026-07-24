/**
 * CategoryCard — the icon-based category card (used on /resources "Explore by Category").
 * Has an icon, title, body, and a "X+ Resources →" link.
 */
"use client";

import { m } from "framer-motion";

import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { cardHover, fadeUp } from "@/lib/animations";

export interface CategoryItem {
  title: string;
  body: string;
  resourceCount: number;
  icon: React.ReactNode;
  href: string;
}

export interface CategoryCardProps {
  items: CategoryItem[];
  className?: string;
}

export function CategoryCard({ items, className }: CategoryCardProps) {
  return (
    <StaggerContainer
      className={className ?? "grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6"}
      staggerDelay={0.06}
    >
      {items.map((cat) => (
        <MotionItem
          key={cat.title}
          variant="fadeUp"
          className="group rounded-2xl border border-white/10 bg-white/[0.02] p-5 transition-colors hover:border-emerald-400/30"
        >
          <m.div
            variants={cardHover}
            initial="rest"
            whileHover="hover"
            animate="rest"
            className="flex flex-col items-center text-center"
          >
            <m.div
              whileHover={{ scale: 1.1, rotate: 4 }}
              transition={{ type: "spring", stiffness: 300, damping: 15 }}
              className="grid h-12 w-12 place-items-center rounded-xl border border-emerald-400/20 bg-emerald-400/5 text-emerald-300"
            >
              {cat.icon}
            </m.div>
            <h3 className="mt-3 text-sm font-semibold text-white">{cat.title}</h3>
            <p className="mt-1 text-xs text-white/60">{cat.body}</p>
            <a
              href={cat.href}
              className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-lime-300 transition-colors hover:text-lime-200"
            >
              {cat.resourceCount}+ Resources <ArrowRight />
            </a>
          </m.div>
        </MotionItem>
      ))}
    </StaggerContainer>
  );
}

function ArrowRight() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
      <path
        d="M2 5h6m0 0L5 2m3 3L5 8"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export { fadeUp };
