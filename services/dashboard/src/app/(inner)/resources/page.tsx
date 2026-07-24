/**
 * /resources — "Knowledge Today. Sustainability Tomorrow."
 *
 * Layout matches the design:
 *  - Hero: breadcrumb + badge + headline + search + popular tags (left) +
 *          globe visual with stats sidebar (right)
 *  - "Explore by Category" — 6 category cards
 *  - "Featured Resources" — 5 resource cards
 *  - "Tools & Templates" — 4 tool cards + CTA card
 *  - Newsletter signup
 *  - Trusted-by (provided by inner layout)
 *
 * All data is sourced from `@/lib/data` (CATEGORIES, FEATURED_RESOURCES,
 * TOOLS, RESOURCE_STATS, POPULAR_TAGS).
 */
"use client";

import {
  CATEGORIES,
  FEATURED_RESOURCES,
  TOOLS,
  RESOURCE_STATS,
  POPULAR_TAGS,
} from "@/lib/data";

import { CategoryCard } from "@/components/sections/category-card";
import { CtaBanner } from "@/components/sections/cta-banner";
import { ResourceCard } from "@/components/sections/resource-card";
import { StatGrid } from "@/components/sections/stat-grid";
import { TrustedBy } from "@/components/landing/trusted-by";
import { MotionButton } from "@/components/motion/motion-button";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp } from "@/lib/animations";
import { m } from "framer-motion";

/* ─────────────────  Page  ───────────────── */
export default function ResourcesPage() {
  return (
    <main>
      {/* Hero with breadcrumb + headline + search (left) + globe + stats sidebar (right) */}
      <section className="relative isolate overflow-hidden pb-16 pt-10 md:pb-24 md:pt-16">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(ellipse at 80% 0%, rgba(132,204,22,0.15) 0%, transparent 50%), radial-gradient(ellipse at 0% 100%, rgba(16,185,129,0.1) 0%, transparent 50%)",
          }}
        />
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-6 md:grid-cols-2">
          {/* LEFT */}
          <StaggerContainer className="flex flex-col">
            <MotionItem variant="fadeIn" className="flex items-center gap-1 text-sm text-white/60">
              <a href="/" className="hover:text-white">Home</a>
              <ChevronIcon /> <span className="text-white">Resources</span>
            </MotionItem>
            <MotionItem variant="fadeIn" className="mt-6">
              <CenterBadge>Knowledge for Impact</CenterBadge>
            </MotionItem>
            <h1 className="mt-4 text-4xl font-extrabold leading-[1.1] tracking-tight text-white md:text-5xl lg:text-6xl">
              Knowledge Today.
              <span className="ml-2 block bg-gradient-to-r from-lime-300 via-emerald-300 to-lime-300 bg-clip-text text-transparent">
                Sustainability Tomorrow.
              </span>
            </h1>
            <MotionItem variant="fadeUp">
              <p className="mt-5 max-w-lg text-base leading-relaxed text-white/70 md:text-lg">
                Explore guides, tools, templates, and expert insights to help you measure, reduce, and maximize your impact.
              </p>
            </MotionItem>
            <MotionItem variant="fadeUp">
              <ResourcesSearch />
            </MotionItem>
            <MotionItem variant="fadeUp">
              <PopularTagsRow />
            </MotionItem>
          </StaggerContainer>

          {/* RIGHT */}
          <div className="relative">
            <GlobeVisual />
            <div className="mt-6">
              <StatGrid stats={RESOURCE_STATS.map(toStat)} variant="sidebar" />
            </div>
          </div>
        </div>
      </section>

      {/* Explore by Category */}
      <section className="border-y border-white/5 py-14">
        <div className="mx-auto max-w-7xl px-6">
          <div className="mb-8 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
            <h2 className="text-2xl font-bold text-white md:text-3xl">
              Explore by <span className="text-lime-300">Category</span>
            </h2>
            <a
              href="/resources/categories"
              className="inline-flex items-center gap-1 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1.5 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-400/10"
            >
              View All Categories <ArrowRight />
            </a>
          </div>
          <CategoryCard items={CATEGORIES.map(toCategory)} className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6" />
        </div>
      </section>

      {/* Featured Resources */}
      <section className="py-14">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeader
            title={<>Featured <span className="text-lime-300">Resources</span></>}
            subtitle="Handpicked content to help you take meaningful action."
            action={{ label: "View All Resources", href: "/resources/all" }}
          />
          <ResourceCard items={FEATURED_RESOURCES.map(toResource)} />
        </div>
      </section>

      {/* Tools & Templates */}
      <section className="border-t border-white/5 py-14">
        <div className="mx-auto max-w-7xl px-6">
          <SectionHeader
            title={<>Tools & <span className="text-lime-300">Templates</span></>}
            subtitle="Practical resources to simplify your sustainability workflow."
            action={{ label: "Browse All Tools", href: "/resources/tools" }}
          />
          <ToolsGrid tools={TOOLS.map(toTool)} />
        </div>
      </section>

      {/* Join community banner */}
      <CtaBanner
        variant="minimal"
        heading="Join a global community"
        highlight={<span className="block text-lime-300">of sustainability leaders.</span>}
        body="Share knowledge. Exchange ideas. Create impact together."
        primary={{ label: "Join Community" }}
        features={["Trusted by organizations worldwide"]}
      />

      {/* Newsletter */}
      <NewsletterBanner />

      {/* Trusted-by row (inner layout has Footer; this is the logos row) */}
      <TrustedBy />
    </main>
  );
}

/* ─────────────────  Data adapters  ───────────────── */
// Each consumer expects slightly different shapes. These adapters keep
// the data file clean (string keys) and the consumers simple.
const ICON: Record<string, React.ReactNode> = {
  book: <BookIcon />,
  chart: <ChartIcon />,
  tool: <ToolIcon />,
  video: <VideoIcon />,
  case: <CaseIcon />,
  shield: <ShieldIcon />,
  calc: <CalcIcon />,
  db: <DbIcon />,
  doc: <DocIcon />,
  target: <TargetIcon />,
  person: <PersonIcon />,
  group: <GroupIcon />,
  globe: <GlobeIcon />,
  cloud: <CloudIcon />,
  trend: <TrendIcon />,
  hub: <HubIcon />,
  flow: <FlowIcon />,
  scale: <ScaleIcon />,
  leaf: <LeafIcon />,
  brain: <BrainIcon />,
  accurate: <AccurateIcon />,
  action: <ActionIcon />,
  trans: <TransIcon />,
};

function toStat(s: typeof RESOURCE_STATS[number]) {
  return {
    value: s.value,
    suffix: s.suffix,
    label: s.label,
    icon: ICON[s.icon],
  };
}
function toCategory(c: typeof CATEGORIES[number]) {
  return {
    title: c.title,
    body: c.body,
    resourceCount: c.resourceCount,
    href: c.href,
    icon: ICON[c.icon],
  };
}
function toResource(r: typeof FEATURED_RESOURCES[number]) {
  return {
    type: r.type,
    title: r.title,
    body: r.body,
    meta: r.meta,
    level: r.level,
    image: r.image,
    alt: r.alt,
    href: r.href,
  };
}
function toTool(t: typeof TOOLS[number]) {
  return {
    title: t.title,
    body: t.body,
    cta: t.cta,
    icon: ICON[t.icon],
  };
}

/* ─────────────────  Sub-components  ───────────────── */
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

function ChevronIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-white/40">
      <path d="M4 2L8 6L4 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ResourcesSearch() {
  return (
    <div className="mt-6 flex max-w-xl flex-col gap-2 sm:flex-row">
      <div className="flex flex-1 items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2.5">
        <SearchIcon />
        <input
          type="text"
          placeholder="Search resources..."
          className="w-full bg-transparent text-sm text-white placeholder:text-white/40 focus:outline-none"
        />
      </div>
      <select className="rounded-full border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white focus:outline-none">
        <option className="bg-[#0a1410]">All Resources</option>
        <option className="bg-[#0a1410]">Guides</option>
        <option className="bg-[#0a1410]">Templates</option>
        <option className="bg-[#0a1410]">Reports</option>
      </select>
    </div>
  );
}

function PopularTagsRow() {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-white/60">
      <span>Popular:</span>
      {POPULAR_TAGS.map((tag) => (
        <span key={tag} className="rounded-full border border-white/10 bg-white/[0.02] px-3 py-1 text-xs">
          {tag}
        </span>
      ))}
    </div>
  );
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-white/50">
      <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M11 11L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function GlobeVisual() {
  return (
    <div className="relative aspect-square w-full">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -inset-6 -z-10 rounded-full opacity-50"
        style={{
          background:
            "radial-gradient(circle, rgba(132,204,22,0.18) 0%, transparent 70%)",
        }}
      />
      <svg viewBox="0 0 100 100" className="h-full w-full">
        <defs>
          <radialGradient id="globe" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgba(132,204,22,0.6)" />
            <stop offset="100%" stopColor="rgba(56,189,248,0.0)" />
          </radialGradient>
        </defs>
        <circle cx="50" cy="50" r="42" fill="url(#globe)" />
        <circle cx="50" cy="50" r="32" fill="none" stroke="rgba(132,204,22,0.5)" strokeWidth="1" />
        <text x="50" y="54" textAnchor="middle" fontSize="6" fill="rgba(255,255,255,0.9)" fontWeight="700">E</text>
      </svg>
    </div>
  );
}

function SectionHeader({ title, subtitle, action }: { title: React.ReactNode; subtitle?: string; action?: { label: string; href: string } }) {
  return (
    <div className="mb-8 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <h2 className="text-2xl font-bold text-white md:text-3xl">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-white/60">{subtitle}</p>}
      </div>
      {action && (
        <a
          href={action.href}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1.5 text-xs font-medium text-emerald-300 transition-colors hover:bg-emerald-400/10"
        >
          {action.label} <ArrowRight />
        </a>
      )}
    </div>
  );
}

function ToolsGrid({ tools }: { tools: ReturnType<typeof toTool>[] }) {
  return (
    <StaggerContainer className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-5" staggerDelay={0.08}>
      {tools.map((tool) => (
        <MotionItem
          key={tool.title}
          variant="fadeUp"
          className="group flex flex-col rounded-2xl border border-white/10 bg-white/[0.02] p-5 transition-colors hover:border-emerald-400/30"
        >
          <div className="mb-4 grid h-10 w-10 place-items-center rounded-xl border border-emerald-400/20 bg-emerald-400/5 text-emerald-300">
            {tool.icon}
          </div>
          <h3 className="text-sm font-semibold text-white">{tool.title}</h3>
          <p className="mt-1 flex-1 text-xs text-white/60">{tool.body}</p>
          <a
            href="#"
            className="mt-3 inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-white transition-colors group-hover:border-emerald-400/30 group-hover:bg-emerald-400/5"
          >
            {tool.cta} <ArrowRight />
          </a>
        </MotionItem>
      ))}
      <MotionItem
        variant="fadeUp"
        className="flex flex-col items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-5 text-center"
      >
        <p className="text-sm font-semibold text-white">Everything you need, in one place.</p>
        <p className="mt-1 text-xs text-white/60">Save time, ensure accuracy, and drive real impact.</p>
        <a
          href="#"
          className="mt-3 inline-flex items-center gap-1 rounded-md bg-lime-300 px-3 py-1.5 text-xs font-semibold text-black transition-colors hover:bg-lime-200"
        >
          Explore All Resources <ArrowRight />
        </a>
      </MotionItem>
    </StaggerContainer>
  );
}

function NewsletterBanner() {
  return (
    <section className="border-y border-white/5 bg-white/[0.02] py-12">
      <div className="mx-auto grid max-w-7xl items-center gap-6 px-6 md:grid-cols-2">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
            <GroupIcon />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Stay informed. Make an impact.</h3>
            <p className="mt-1 text-sm text-white/60">Get the latest insights, tools, and sustainability updates — straight to your inbox.</p>
          </div>
        </div>
        <form className="flex flex-col gap-2 sm:flex-row">
          <input
            type="email"
            placeholder="Enter your email"
            className="flex-1 rounded-full border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder:text-white/40 focus:border-emerald-400/50 focus:outline-none"
          />
          <MotionButton type="submit" size="md" iconAfter={<ArrowRight />}>
            Subscribe
          </MotionButton>
        </form>
        <p className="text-xs text-white/50 md:col-span-2">No spam. Unsubscribe anytime.</p>
      </div>
    </section>
  );
}

/* ─────────────────  Icons  ───────────────── */
function ArrowRight() {
  return <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 6h7m0 0L6 3m3 3L6 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
function BookIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M4 5a2 2 0 012-2h12a2 2 0 012 2v14H6a2 2 0 01-2-2V5z" strokeLinejoin="round" /><path d="M4 17h14" /></svg>; }
function ChartIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M3 21h18M6 17V9M11 17V5M16 17v-6M21 17v-3" strokeLinecap="round" /></svg>; }
function ToolIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M10 10h4v4h-4z" /></svg>; }
function VideoIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M10 9l5 3-5 3V9z" fill="currentColor" /></svg>; }
function CaseIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M3 7h18v13H3z" /><path d="M3 7l3-3h12l3 3" strokeLinejoin="round" /></svg>; }
function ShieldIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 3l8 3v5c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-3z" /></svg>; }
function CalcIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><rect x="4" y="3" width="16" height="18" rx="2" /><rect x="7" y="6" width="10" height="3" /><circle cx="9" cy="14" r="1" fill="currentColor" /><circle cx="15" cy="14" r="1" fill="currentColor" /></svg>; }
function DbIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></svg>; }
function DocIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" strokeLinejoin="round" /></svg>; }
function TargetIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /></svg>; }
function PersonIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-7 8-7s8 3 8 7" /></svg>; }
function GroupIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M3 19c0-3 2.5-5 6-5s6 2 6 5" /></svg>; }
function GlobeIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></svg>; }
function CloudIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M7 18a4 4 0 010-8 6 6 0 0111.5 1.5A4 4 0 0118 18H7z" strokeLinejoin="round" /></svg>; }
function TrendIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M3 17l4-4 3 3 7-7M14 6h4v4" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function HubIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 7l3 3M17 7l-3 3M7 17l3-3M17 17l-3-3" /></svg>; }
function FlowIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="3" width="6" height="6" rx="1" /><rect x="9" y="15" width="6" height="6" rx="1" /><path d="M6 9v3h12V9" /><path d="M12 12v3" /></svg>; }
function ScaleIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 3v18M5 7l7-4 7 4M5 7v4a2 2 0 002 2h6a2 2 0 002-2V7" /></svg>; }
function LeafIcon() { return <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5"><path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" /></svg>; }
function BrainIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M9 4a3 3 0 00-3 3v2a3 3 0 00-2 5 3 3 0 002 5v2a3 3 0 003 3 3 3 0 003-3V4a3 3 0 00-3 0z" strokeLinejoin="round" /></svg>; }
function AccurateIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M3 17l4-4 3 3 7-7M14 6h4v4" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function ActionIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 2l3 6 6 1-4.5 4 1 6L12 16l-5.5 3 1-6L3 9l6-1z" strokeLinejoin="round" /></svg>; }
function TransIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z" /></svg>; }
