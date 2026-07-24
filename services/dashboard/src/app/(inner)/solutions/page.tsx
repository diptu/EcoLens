/**
 * /solutions — "Smarter Solutions for a Sustainable Future"
 *
 * Layout matches the design:
 *  - Hero: breadcrumb + SOLUTIONS FOR EVERY IMPACT badge + headline + 3 feature pills +
 *          GlobeWithIndustryIcons (CSS-only rotation)
 *  - 5 industry photo cards + "Don't see your industry?" CTA bar
 *  - 6 platform features (OUR PLATFORM. YOUR ADVANTAGE)
 *  - 4 stat cards (Real Impact. Measurable Results.)
 *  - Final CTA
 *
 * All data is sourced from `@/lib/data` (INDUSTRIES, PLATFORM_FEATURES,
 * SOLUTIONS_STATS). Edit the data file to change content globally.
 */
"use client";

import {
  INDUSTRIES,
  PLATFORM_FEATURES,
  SOLUTIONS_STATS,
} from "@/lib/data";

import { CtaBanner } from "@/components/sections/cta-banner";
import { IndustryGrid } from "@/components/sections/industry-grid";
import { StatGrid } from "@/components/sections/stat-grid";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { fadeUp, staggerContainer } from "@/lib/animations";
import { m } from "framer-motion";

/* ─────────────────  Globe with industry icons (CSS-only)  ───────────────── */
function GlobeWithIndustryIcons() {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-md">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -inset-10 -z-10 rounded-full opacity-50"
        style={{
          background: "radial-gradient(circle, rgba(132,204,22,0.18) 0%, transparent 70%)",
        }}
      />
      <div className="relative h-full w-full">
        <div className="absolute left-1/2 top-1/2 h-32 w-32 -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-br from-emerald-400/30 via-sky-400/20 to-lime-300/30">
          <div className="absolute inset-3 rounded-full border border-emerald-400/30" />
          <div className="absolute inset-6 rounded-full border border-sky-400/20" />
          <div className="grid h-full w-full place-items-center">
            <span className="text-3xl font-bold text-white/80">E</span>
          </div>
        </div>
        <div className="solutions-orbit absolute inset-0">
          {[
            { label: "Measure Accurately", icon: <PinIcon />, top: "10%", left: "50%", translate: "-50% 0" },
            { label: "AI Insights", icon: <BrainIcon />, top: "50%", left: "10%", translate: "0 -50%" },
            { label: "Act Decisively", icon: <RocketIcon />, top: "50%", left: "90%", translate: "0 -50%" },
            { label: "Reduce Emissions", icon: <LeafIcon />, top: "90%", left: "50%", translate: "-50% 0" },
          ].map((item) => (
            <div
              key={item.label}
              className="solutions-orbit-counter absolute"
              style={{ top: item.top, left: item.left, transform: `translate(${item.translate})` }}
            >
              <div className="flex flex-col items-center gap-1">
                <div className="grid h-14 w-14 place-items-center rounded-full border border-emerald-400/30 bg-emerald-400/10 text-emerald-300 shadow-[0_0_30px_rgba(132,204,22,0.4)]">
                  {item.icon}
                </div>
                <span className="rounded-md bg-black/60 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur">
                  {item.label}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const PILL_FEATURES = [
  { title: "AI-Powered Intelligence", body: "Smart algorithms to turn complex data into clear actions." },
  { title: "Scalable & Flexible", body: "Built to grow with your organization, from startup to enterprise." },
  { title: "Secure & Enterprise Ready", body: "SOC 2, ISO 27001, and GDPR compliant." },
];

const ICON: Record<string, React.ReactNode> = {
  brain: <BrainIcon />,
  hub: <HubIcon />,
  flow: <FlowIcon />,
  shield: <ShieldIcon />,
  scale: <ScaleIcon />,
  globe: <GlobeIcon />,
  cloud: <CloudIcon />,
  trend: <TrendIcon />,
  group: <GroupIcon />,
  leaf: <LeafIcon />,
};

/* ─────────────────  Page  ───────────────── */
export default function SolutionsPage() {
  return (
    <main>
      <section className="relative isolate overflow-hidden pb-16 pt-10 md:pb-24 md:pt-16">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(ellipse at 0% 0%, rgba(132,204,22,0.15) 0%, transparent 50%), radial-gradient(ellipse at 100% 100%, rgba(16,185,129,0.1) 0%, transparent 50%)",
          }}
        />
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-6 md:grid-cols-2">
          {/* LEFT */}
          <StaggerContainer className="flex flex-col">
            <MotionItem variant="fadeIn" className="flex items-center gap-1 text-sm text-white/60">
              <a href="/" className="hover:text-white">Home</a>
              <ChevronIcon /> <span className="text-white">Solutions</span>
            </MotionItem>
            <MotionItem variant="fadeIn" className="mt-6">
              <m.span
                variants={fadeUp}
                className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium tracking-wider text-emerald-300"
              >
                <span className="grid h-4 w-4 place-items-center rounded-full bg-emerald-400/20">
                  <svg viewBox="0 0 8 8" fill="currentColor" className="h-2.5 w-2.5">
                    <path d="M4 0L4.6 3.4L8 4L4.6 4.6L4 8L3.4 4.6L0 4L3.4 3.4Z" />
                  </svg>
                </span>
                SOLUTIONS FOR EVERY IMPACT
              </m.span>
            </MotionItem>
            <h1 className="mt-4 text-4xl font-extrabold leading-[1.1] tracking-tight text-white md:text-5xl lg:text-6xl">
              Smarter Solutions
              <span className="ml-2 block bg-gradient-to-r from-lime-300 via-emerald-300 to-lime-300 bg-clip-text text-transparent">
                for a Sustainable Future
              </span>
            </h1>
            <MotionItem variant="fadeUp">
              <p className="mt-5 max-w-lg text-base leading-relaxed text-white/70 md:text-lg">
                Tailored carbon intelligence solutions to help every industry measure, manage, and reduce environmental impact.
              </p>
            </MotionItem>
            <StaggerContainer className="mt-8 grid grid-cols-1 gap-5 sm:grid-cols-3" staggerDelay={0.08}>
              {PILL_FEATURES.map((f) => (
                <MotionItem key={f.title} variant="fadeUp" className="flex items-start gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-emerald-400/20 bg-emerald-400/5 text-emerald-300">
                    <CheckIcon />
                  </span>
                  <div>
                    <h4 className="text-sm font-semibold text-white">{f.title}</h4>
                    <p className="mt-0.5 text-xs text-white/60">{f.body}</p>
                  </div>
                </MotionItem>
              ))}
            </StaggerContainer>
          </StaggerContainer>

          {/* RIGHT */}
          <GlobeWithIndustryIcons />
        </div>
      </section>

      {/* Industries */}
      <section className="py-14">
        <div className="mx-auto max-w-7xl px-6">
          <div className="mb-8 text-center">
            <m.span
              variants={fadeUp}
              className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium tracking-wider text-emerald-300"
            >
              <span className="grid h-4 w-4 place-items-center rounded-full bg-emerald-400/20">
                <svg viewBox="0 0 8 8" fill="currentColor" className="h-2.5 w-2.5">
                  <path d="M4 0L4.6 3.4L8 4L4.6 4.6L4 8L3.4 4.6L0 4L3.4 3.4Z" />
                </svg>
              </span>
              INDUSTRIES WE SERVE
            </m.span>
            <h2 className="mt-4 text-2xl font-bold text-white md:text-3xl">
              Solutions Tailored to <span className="text-lime-300">Your Industry</span>
            </h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-white/60">
              Every industry has unique challenges. We build solutions to match.
            </p>
          </div>
          <IndustryGrid
            items={INDUSTRIES.map((i) => ({ ...i }))}
            bottomCta={{ label: "Don't see your industry? Talk to us", href: "/contact" }}
          />
        </div>
      </section>

      {/* Platform features */}
      <section className="border-t border-white/5 py-14">
        <div className="mx-auto max-w-7xl px-6">
          <div className="mb-8 text-center">
            <m.span
              variants={fadeUp}
              className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium tracking-wider text-emerald-300"
            >
              <span className="grid h-4 w-4 place-items-center rounded-full bg-emerald-400/20">
                <svg viewBox="0 0 8 8" fill="currentColor" className="h-2.5 w-2.5">
                  <path d="M4 0L4.6 3.4L8 4L4.6 4.6L4 8L3.4 4.6L0 4L3.4 3.4Z" />
                </svg>
              </span>
              OUR PLATFORM. YOUR ADVANTAGE
            </m.span>
            <h2 className="mt-4 text-2xl font-bold text-white md:text-3xl">
              One Platform. <span className="text-lime-300">Endless Possibilities</span>
            </h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-white/60">
              Everything you need to power your sustainability journey.
            </p>
          </div>
          <m.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-50px" }}
            variants={staggerContainer}
            className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3"
          >
            {PLATFORM_FEATURES.map((f) => (
              <m.div
                key={f.title}
                variants={fadeUp}
                whileHover={{ y: -4, scale: 1.015 }}
                className="group flex flex-col rounded-2xl border border-white/10 bg-white/[0.02] p-6 transition-colors hover:border-emerald-400/30"
              >
                <div className="mb-4 grid h-12 w-12 place-items-center rounded-xl border border-emerald-400/20 bg-emerald-400/5 text-emerald-300">
                  {ICON[f.icon]}
                </div>
                <h3 className="text-lg font-semibold text-white">{f.title}</h3>
                <p className="mt-1 flex-1 text-sm text-white/60">{f.body}</p>
                <a
                  href="#"
                  className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-emerald-300 opacity-0 transition-opacity group-hover:opacity-100"
                >
                  Explore {f.title} <ArrowRight />
                </a>
              </m.div>
            ))}
          </m.div>
        </div>
      </section>

      {/* Stats */}
      <section className="py-14">
        <div className="mx-auto max-w-7xl px-6 text-center">
          <h2 className="text-2xl font-bold text-white md:text-3xl">
            Real Impact. <span className="text-lime-300">Measurable Results.</span>
          </h2>
          <p className="mx-auto mt-2 max-w-xl text-sm text-white/60">
            Built on outcomes that matter — measurable reductions, verified by independent partners.
          </p>
          <div className="mt-10">
            <StatGrid
              stats={SOLUTIONS_STATS.map((s) => ({ value: s.value, suffix: s.suffix, label: s.label, icon: ICON[s.icon] }))}
              variant="cards"
            />
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <CtaBanner
        badge="Let's Build a Better Tomorrow"
        heading="Your goals."
        highlight={<span className="block bg-gradient-to-r from-lime-300 to-emerald-300 bg-clip-text text-transparent">Our solutions. A better planet for all.</span>}
        body="EcoLens is a carbon intelligence platform that empowers businesses to drive real impact at scale."
        primary={{ label: "Get Started" }}
        secondary={{ label: "Book a Demo" }}
        features={["No credit card required", "Free forever plan available"]}
      />
    </main>
  );
}

/* ─────────────────  Icons  ───────────────── */
function ChevronIcon() { return <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-white/40"><path d="M4 2L8 6L4 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function ArrowRight() { return <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 6h7m0 0L6 3m3 3L6 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function CheckIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function PinIcon() { return <svg viewBox="0 0 24 24" fill="currentColor" className="h-6 w-6"><path d="M12 2C8 2 5 5 5 9c0 5 7 13 7 13s7-8 7-13c0-4-3-7-7-7zm0 9.5a2.5 2.5 0 110-5 2.5 2.5 0 010 5z" /></svg>; }
function BrainIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><path d="M9 4a3 3 0 00-3 3v2a3 3 0 00-2 5 3 3 0 002 5v2a3 3 0 003 3 3 3 0 003-3V4a3 3 0 00-3 0z" strokeLinejoin="round" /></svg>; }
function RocketIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><path d="M12 2c4 4 6 8 6 12l-3 3-3-3-3 3-3-3c0-4 2-8 6-12z" strokeLinejoin="round" /><circle cx="12" cy="11" r="2" fill="currentColor" /></svg>; }
function LeafIcon() { return <svg viewBox="0 0 24 24" fill="currentColor" className="h-6 w-6"><path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" /></svg>; }
function HubIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 7l3 3M17 7l-3 3M7 17l3-3M17 17l-3-3" /></svg>; }
function FlowIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="3" width="6" height="6" rx="1" /><rect x="9" y="15" width="6" height="6" rx="1" /><path d="M6 9v3h12V9" /><path d="M12 12v3" /></svg>; }
function ShieldIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><path d="M12 3l8 3v5c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-3z" /></svg>; }
function ScaleIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><path d="M12 3v18M5 7l7-4 7 4M5 7v4a2 2 0 002 2h6a2 2 0 002-2V7" /></svg>; }
function GlobeIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></svg>; }
function CloudIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><path d="M7 18a4 4 0 010-8 6 6 0 0111.5 1.5A4 4 0 0118 18H7z" strokeLinejoin="round" /></svg>; }
function TrendIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><path d="M3 17l4-4 3 3 7-7M14 6h4v4" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function GroupIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-6 w-6"><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M3 19c0-3 2.5-5 6-5s6 2 6 5" /></svg>; }
