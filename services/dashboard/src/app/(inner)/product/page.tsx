/**
 * /product — "All-in-one Carbon Intelligence Platform"
 *
 * Layout matches the design:
 *  - Hero: breadcrumb + OUR PRODUCT badge + headline + 3 feature pills + dashboard mockup
 *  - Trusted-by row
 *  - 6-feature grid (POWERFUL FEATURES)
 *  - 4-step "From Data to Impact" flow (HOW IT WORKS)
 *  - Final CTA (forest background)
 *
 * All data is sourced from `@/lib/data` (PRODUCT_FEATURES, PRODUCT_STEPS,
 * PRODUCT_PILL_FEATURES). Edit the data file to change content globally.
 */
import {
  PRODUCT_FEATURES,
  PRODUCT_PILL_FEATURES,
  PRODUCT_STEPS,
} from "@/lib/data";

import { CtaBanner } from "@/components/sections/cta-banner";
import {
  FeatureGrid,
  FunnelVisual,
  BrainVisual,
  ChartVisual,
  DonutVisual,
  ReportVisual,
  WindTurbineVisual,
} from "@/components/sections/feature-grid";
import { PageHero } from "@/components/sections/page-hero";
import { StepFlow } from "@/components/sections/step-flow";
import { TrustedBy } from "@/components/landing/trusted-by";
import { StaggerContainer, MotionItem } from "@/components/motion/motion-section";
import { m } from "framer-motion";

/* ─────────────────  Dashboard mockup (right side of hero)  ───────────────── */
function DashboardMockup() {
  return (
    <div className="relative">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -inset-6 -z-10 rounded-3xl opacity-60"
        style={{
          background:
            "radial-gradient(circle, rgba(132,204,22,0.18) 0%, transparent 70%)",
        }}
      />
      <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0a1410] shadow-[0_30px_80px_-30px_rgba(132,204,22,0.45)]">
        {/* Top bar */}
        <div className="flex items-center gap-2 border-b border-white/5 px-4 py-3">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-emerald-400/15 text-emerald-300 text-[10px] font-bold">E</span>
          <span className="text-xs font-semibold text-white">EcoLens</span>
          <span className="text-xs text-white/50">· Overview</span>
          <span className="ml-auto rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-white/60">This Month ▾</span>
        </div>
        <div className="grid grid-cols-12 gap-3 p-3 text-[10px]">
          {/* Sidebar */}
          <div className="col-span-3 space-y-1">
            {[
              { label: "Overview", active: true },
              { label: "Emissions", active: false },
              { label: "Sources", active: false },
              { label: "Reports", active: false },
              { label: "Goals", active: false },
              { label: "Actions", active: false },
              { label: "Data Sources", active: false },
              { label: "Settings", active: false },
            ].map((item) => (
              <div
                key={item.label}
                className={`flex items-center gap-1.5 rounded-md px-2 py-1.5 ${
                  item.active ? "bg-emerald-400/10 text-emerald-300" : "text-white/60"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${item.active ? "bg-emerald-400" : "bg-white/30"}`} />
                <span>{item.label}</span>
              </div>
            ))}
          </div>
          {/* Main content */}
          <div className="col-span-9 space-y-3">
            {/* KPI row */}
            <div className="grid grid-cols-4 gap-2">
              {[
                { label: "Total Emissions", value: "2,453", sub: "tCO₂e", change: "↓ 18% vs last month", color: "text-emerald-400" },
                { label: "Emission Intensity", value: "0.42", sub: "tCO₂e / $ revenue", change: "↓ 12% vs last month", color: "text-emerald-400" },
                { label: "Total Reduction", value: "28%", sub: "vs baseline", change: "↑ 28% vs baseline", color: "text-emerald-400" },
                { label: "Goals Achieved", value: "3/7", sub: "On Track", change: "", color: "text-lime-300" },
              ].map((kpi) => (
                <div key={kpi.label} className="rounded-md border border-white/5 bg-white/[0.02] p-2">
                  <p className="text-[8px] uppercase tracking-wider text-white/40">{kpi.label}</p>
                  <p className="mt-1 text-base font-bold text-white">{kpi.value}</p>
                  <p className="text-[8px] text-white/40">{kpi.sub}</p>
                  {kpi.change && <p className={`mt-0.5 text-[9px] ${kpi.color}`}>{kpi.change}</p>}
                </div>
              ))}
            </div>
            {/* Chart + Donut row */}
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-md border border-white/5 bg-white/[0.02] p-2">
                <p className="text-[8px] uppercase tracking-wider text-white/40">Emissions Over Time</p>
                <div className="mt-1 flex items-center gap-2 text-[8px] text-white/60">
                  <span className="flex items-center gap-1">
                    <span className="h-0.5 w-2 bg-lime-300" /> Current Year
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-0.5 w-2 border-b border-dashed border-white/40" /> Baseline
                  </span>
                </div>
                <svg viewBox="0 0 200 60" className="mt-1 h-12 w-full">
                  <polyline
                    points="0,40 30,30 60,35 90,20 120,25 150,10 180,15 200,5"
                    fill="none"
                    stroke="rgba(132,204,22,0.8)"
                    strokeWidth="1.5"
                  />
                  <polyline
                    points="0,50 30,45 60,40 90,35 120,30 150,25 180,20 200,18"
                    fill="none"
                    stroke="rgba(132,204,22,0.4)"
                    strokeWidth="1.2"
                    strokeDasharray="3 2"
                  />
                </svg>
                <div className="mt-1 flex justify-between text-[7px] text-white/40">
                  {["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"].map((m) => (
                    <span key={m}>{m}</span>
                  ))}
                </div>
              </div>
              <div className="rounded-md border border-white/5 bg-white/[0.02] p-2">
                <p className="text-[8px] uppercase tracking-wider text-white/40">Emissions by Source</p>
                <div className="mt-1 flex items-center gap-2">
                  <div className="relative grid h-12 w-12 place-items-center">
                    <svg viewBox="0 0 36 36" className="h-12 w-12 -rotate-90">
                      <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="4" />
                      <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(132,204,22,0.9)" strokeWidth="4" strokeDasharray="35 88" />
                      <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(16,185,129,0.8)" strokeWidth="4" strokeDasharray="22 88" strokeDashoffset="-35" />
                      <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(56,189,248,0.7)" strokeWidth="4" strokeDasharray="13 88" strokeDashoffset="-57" />
                      <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(168,85,247,0.6)" strokeWidth="4" strokeDasharray="9 88" strokeDashoffset="-70" />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                      <span className="text-[8px] font-bold text-white">2,453</span>
                      <span className="text-[6px] text-white/40">tCO₂e</span>
                    </div>
                  </div>
                  <div className="space-y-0.5 text-[9px]">
                    {[
                      { color: "bg-lime-300", label: "Electricity", pct: "40%" },
                      { color: "bg-emerald-400", label: "Transportation", pct: "25%" },
                      { color: "bg-sky-400", label: "Stationary Fuel", pct: "15%" },
                      { color: "bg-purple-400", label: "Waste", pct: "10%" },
                      { color: "bg-white/40", label: "Others", pct: "10%" },
                    ].map((row) => (
                      <p key={row.label} className="flex items-center gap-1 text-white/70">
                        <span className={`h-1.5 w-1.5 rounded-full ${row.color}`} /> {row.label} {row.pct}
                      </p>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────  Icon map (used by FeatureGrid)  ───────────────── */
const ICON_MAP: Record<string, React.ReactNode> = {
  cloud: <CloudIcon />,
  brain: <BrainIcon />,
  chart: <ChartIcon />,
  target: <TargetIcon />,
  doc: <DocIcon />,
  leaf: <LeafIcon />,
  globe: <GlobeIcon />,
};

const VISUAL_MAP: Record<string, React.ReactNode> = {
  funnel: <FunnelVisual />,
  brain: <BrainVisual />,
  chart: <ChartVisual />,
  donut: <DonutVisual percent={72} />,
  report: <ReportVisual />,
  wind: <WindTurbineVisual />,
};

// Map raw data → FeatureGrid input shape (spread to strip readonly)
const FEATURES = PRODUCT_FEATURES.map((f) => ({
  title: f.title,
  body: f.body,
  bullets: [...f.bullets],
  icon: ICON_MAP[f.icon],
  visual: VISUAL_MAP[f.visual],
}));

const STEPS = PRODUCT_STEPS.map((s) => ({
  number: s.number,
  title: s.title,
  body: s.body,
  icon: ICON_MAP[s.icon],
}));

/* ─────────────────  Page  ───────────────── */
export default function ProductPage() {
  return (
    <main>
      <PageHero
        breadcrumb={[
          { label: "Home", href: "/" },
          { label: "Product" },
        ]}
        badge="Our Product"
        title="All-in-one Carbon"
        highlight="Intelligence Platform"
        subtitle="EcoLens combines AI, scientific models, and seamless data workflows to help organizations measure, understand, and reduce their carbon footprint — at scale."
        visual={<DashboardMockup />}
        meta={
          <StaggerContainer className="grid grid-cols-1 gap-5 sm:grid-cols-3" staggerDelay={0.08}>
            {PRODUCT_PILL_FEATURES.map((f) => (
              <MotionItem key={f.title} variant="fadeUp" className="flex items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-emerald-400/20 bg-emerald-400/5 text-emerald-300">
                  {ICON_MAP[f.icon]}
                </span>
                <div>
                  <h4 className="text-sm font-semibold text-white">{f.title}</h4>
                  <p className="mt-0.5 text-xs text-white/60">{f.body}</p>
                </div>
              </MotionItem>
            ))}
          </StaggerContainer>
        }
      />

      <TrustedBy />

      <FeatureGrid
        badge="Powerful Features"
        heading={
          <>
            Everything you need to drive <span className="text-lime-300">real impact</span>
          </>
        }
        items={FEATURES}
      />

      <StepFlow
        badge="How it Works"
        heading={
          <>
            From Data to Impact in <span className="text-lime-300">4 Simple Steps</span>
          </>
        }
        steps={STEPS}
      />

      <CtaBanner
        badge="Ready to Build a Better Tomorrow"
        heading="Ready to make"
        highlight={<span className="block bg-gradient-to-r from-lime-300 to-emerald-300 bg-clip-text text-transparent">sustainability your competitive advantage?</span>}
        body="Join thousands of organizations using EcoLens to build a cleaner, greener tomorrow."
        primary={{ label: "Get Started Free" }}
        secondary={{ label: "Book a Demo" }}
        features={["No credit card required", "Free forever plan available", "Cancel anytime"]}
      />
    </main>
  );
}

/* ─────────────────  Icons  ───────────────── */
function CloudIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4"><path d="M7 18a4 4 0 010-8 6 6 0 0111.5 1.5A4 4 0 0118 18H7z" strokeLinejoin="round" /></svg>;
}
function BrainIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4"><path d="M9 4a3 3 0 00-3 3v2a3 3 0 00-2 5 3 3 0 002 5v2a3 3 0 003 3 3 3 0 003-3V4a3 3 0 00-3 0zM15 4a3 3 0 013 3v2a3 3 0 012 5 3 3 0 01-2 5v2a3 3 0 01-3 3 3 3 0 01-3-3" strokeLinejoin="round" /></svg>;
}
function ChartIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4"><path d="M3 21h18M6 17V9M11 17V5M16 17v-6M21 17v-3" strokeLinecap="round" /></svg>;
}
function TargetIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.5" fill="currentColor" /></svg>;
}
function DocIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" strokeLinejoin="round" /></svg>;
}
function LeafIcon() {
  return <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4"><path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" /></svg>;
}
function GlobeIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></svg>;
}
