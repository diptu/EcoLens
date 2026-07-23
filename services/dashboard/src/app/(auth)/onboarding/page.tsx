/**
 * /onboarding — 6-step organization setup wizard.
 * Two-panel layout: step indicator on the left, current-step form on the right.
 */
"use client";

import { useState } from "react";
import { ArrowRight, Check, ChevronLeft } from "lucide-react";

import {
  AuthLayout,
  AuthField,
  AuthButton,
  AuthDivider,
} from "@/components/auth/auth-layout";

const STEPS = [
  { id: 1, label: "Organization",         sub: "Tell us about your organization" },
  { id: 2, label: "Industry & Operations", sub: "Help us understand your operations" },
  { id: 3, label: "Sustainability Goals", sub: "Set your sustainability objectives" },
  { id: 4, label: "Data & Integrations",  sub: "Connect your data sources" },
  { id: 5, label: "Team Members",         sub: "Invite your team to collaborate" },
  { id: 6, label: "Review & Finish",      sub: "Review and complete setup" },
] as const;

const INDUSTRIES = [
  "Manufacturing",
  "Technology",
  "Retail & E-commerce",
  "Financial Services",
  "Healthcare",
  "Energy & Utilities",
  "Transportation & Logistics",
  "Construction",
  "Agriculture",
  "Other",
];

const COUNTRIES = [
  "Australia",
  "Bangladesh",
  "Canada",
  "Germany",
  "India",
  "Indonesia",
  "Japan",
  "Malaysia",
  "New Zealand",
  "Singapore",
  "United Kingdom",
  "United States",
  "Other",
];

const SIZES = [
  "1–10 employees",
  "11–50 employees",
  "51–200 employees",
  "201–500 employees",
  "501–1,000 employees",
  "1,000+ employees",
];

export default function OnboardingPage() {
  const [step, setStep] = useState<number>(1);
  const next = () => setStep((s) => Math.min(6, s + 1));
  const prev = () => setStep((s) => Math.max(1, s - 1));

  return (
    <AuthLayout
      illustration="steps"
      tagline={<>Welcome to EcoLens! 🎉</>}
      subTagline="Let's get you set up in a few simple steps."
      topSlot={
        <ol className="space-y-1.5">
          {STEPS.map((s) => {
            const active = s.id === step;
            const done = s.id < step;
            return (
              <li
                key={s.id}
                className={
                  "flex items-start gap-3 rounded-lg border p-3 transition-colors " +
                  (active
                    ? "border-emerald-400/40 bg-emerald-400/5"
                    : done
                      ? "border-white/10 bg-white/[0.02]"
                      : "border-transparent bg-transparent")
                }
              >
                <span
                  className={
                    "mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold " +
                    (done
                      ? "bg-emerald-400 text-black"
                      : active
                        ? "bg-emerald-400 text-black"
                        : "border border-white/20 bg-white/5 text-white/40")
                  }
                >
                  {done ? <Check className="h-3.5 w-3.5" /> : s.id}
                </span>
                <div className="min-w-0">
                  <p className={"text-sm font-semibold " + (active || done ? "text-white" : "text-white/70")}>
                    {s.label}
                  </p>
                  <p className="text-[11px] text-white/50">{s.sub}</p>
                </div>
              </li>
            );
          })}
        </ol>
      }
    >
      {/* Right-side header */}
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">{STEPS[step - 1].label}</h1>
        <span className="text-[11px] text-white/40">
          Step {step} of {STEPS.length}
        </span>
      </div>
      <p className="mb-5 text-sm text-white/60">
        {STEPS[step - 1].sub}
      </p>

      {step === 1 && (
        <div className="space-y-4">
          <AuthField
            label="Organization name"
            name="orgName"
            placeholder="Enter organization name"
            autoComplete="organization"
          />
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">Industry</span>
            <select
              name="industry"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white focus:border-emerald-400/60 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
              defaultValue=""
            >
              <option value="" disabled>Select industry</option>
              {INDUSTRIES.map((i) => (
                <option key={i} value={i} className="bg-[#0a1410]">
                  {i}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">Country / Region</span>
            <select
              name="country"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white focus:border-emerald-400/60 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
              defaultValue=""
            >
              <option value="" disabled>Select country or region</option>
              {COUNTRIES.map((c) => (
                <option key={c} value={c} className="bg-[#0a1410]">
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">Organization size</span>
            <select
              name="size"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white focus:border-emerald-400/60 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
              defaultValue=""
            >
              <option value="" disabled>Select organization size</option>
              {SIZES.map((s) => (
                <option key={s} value={s} className="bg-[#0a1410]">
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">Primary operations</span>
            <textarea
              name="ops"
              rows={4}
              placeholder="Describe your core operations (e.g. manufacturing, logistics, retail...)"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white placeholder:text-white/35 focus:border-emerald-400/60 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">Number of facilities</span>
            <AuthField
              label=""
              name="facilities"
              type="number"
              placeholder="e.g. 5"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">Reporting framework</span>
            <select
              name="framework"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white focus:border-emerald-400/60 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
              defaultValue=""
            >
              <option value="" disabled>Select framework</option>
              <option value="ghg" className="bg-[#0a1410]">GHG Protocol</option>
              <option value="sbti" className="bg-[#0a1410]">SBTi</option>
              <option value="tcfd" className="bg-[#0a1410]">TCFD</option>
              <option value="csrd" className="bg-[#0a1410]">CSRD / ESRS</option>
              <option value="other" className="bg-[#0a1410]">Other</option>
            </select>
          </label>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-3">
          {[
            { id: "net-zero", title: "Net Zero by 2050",  sub: "Align with the Paris Agreement" },
            { id: "50pct",    title: "50% reduction by 2030", sub: "Halve emissions in 7 years" },
            { id: "sbti",     title: "SBTi-validated targets", sub: "Science-based, third-party verified" },
            { id: "100renew", title: "100% renewable energy", sub: "RE100 commitment" },
            { id: "scope3",   title: "Reduce Scope 3 by 30%", sub: "Engage your value chain" },
            { id: "custom",   title: "Custom goal", sub: "Define your own targets" },
          ].map((g) => (
            <label
              key={g.id}
              className="flex cursor-pointer items-start gap-3 rounded-md border border-white/10 bg-white/[0.03] p-3 hover:border-emerald-400/40"
            >
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-white/20 bg-white/5 text-emerald-400 focus:ring-emerald-400/30"
              />
              <div>
                <p className="text-sm font-semibold text-white">{g.title}</p>
                <p className="text-[11px] text-white/55">{g.sub}</p>
              </div>
            </label>
          ))}
        </div>
      )}

      {step === 4 && (
        <div className="space-y-3">
          {[
            { name: "AWS CloudTrail",   status: "Available" },
            { name: "Azure Usage",      status: "Available" },
            { name: "Google Cloud",     status: "Available" },
            { name: "Stripe Payments",  status: "Available" },
            { name: "Utility Bills",    status: "Manual upload" },
            { name: "AEMO / NEM / WEM", status: "Coming soon" },
          ].map((i) => (
            <div
              key={i.name}
              className="flex items-center justify-between rounded-md border border-white/10 bg-white/[0.03] p-3"
            >
              <div>
                <p className="text-sm font-semibold text-white">{i.name}</p>
                <p className="text-[11px] text-white/50">{i.status}</p>
              </div>
              <button
                type="button"
                className="rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1 text-[11px] font-medium text-emerald-300 hover:bg-emerald-400/10"
              >
                {i.status === "Available" ? "Connect" : "Learn more"}
              </button>
            </div>
          ))}
        </div>
      )}

      {step === 5 && (
        <div className="space-y-4">
          <p className="text-sm text-white/65">
            Invite teammates to collaborate on your sustainability data.
          </p>
          <AuthField
            label="Email address"
            name="inviteEmail"
            type="email"
            placeholder="teammate@company.com"
          />
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-white/70">Role</span>
            <select
              name="role"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white focus:border-emerald-400/60 focus:outline-none focus:ring-1 focus:ring-emerald-400/30"
              defaultValue="viewer"
            >
              <option value="admin"   className="bg-[#0a1410]">Admin</option>
              <option value="editor"  className="bg-[#0a1410]">Editor</option>
              <option value="analyst" className="bg-[#0a1410]">Analyst</option>
              <option value="viewer"  className="bg-[#0a1410]">Viewer</option>
            </select>
          </label>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white"
          >
            + Invite another
          </button>

          <div className="mt-2 rounded-md border border-white/5 bg-white/[0.02] p-3">
            <p className="text-[10px] uppercase tracking-wider text-white/40">Pending invites</p>
            <p className="mt-1 text-xs text-white/55">No invites sent yet.</p>
          </div>
        </div>
      )}

      {step === 6 && (
        <div className="space-y-4">
          <p className="text-sm text-white/65">
            Here&apos;s a quick summary of your setup. You can always update these later in settings.
          </p>
          {[
            { label: "Organization",   value: "EcoLens Technologies Ltd." },
            { label: "Industry",       value: "Technology" },
            { label: "Country",        value: "Bangladesh" },
            { label: "Size",           value: "11–50 employees" },
            { label: "Framework",      value: "GHG Protocol" },
            { label: "Primary goals",  value: "Net Zero by 2050, 50% reduction by 2030" },
            { label: "Integrations",   value: "AWS CloudTrail, Azure Usage" },
            { label: "Team members",   value: "1 invited" },
          ].map((r) => (
            <div key={r.label} className="flex items-center justify-between border-b border-white/5 pb-2 text-sm last:border-b-0 last:pb-0">
              <span className="text-white/50">{r.label}</span>
              <span className="text-white">{r.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Footer: Back / Next */}
      <div className="mt-6 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={prev}
          disabled={step === 1}
          className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-white/70 hover:bg-white/[0.07] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronLeft className="h-3.5 w-3.5" /> Back
        </button>
        <AuthButton type="button" onClick={next} className="!w-auto flex-1">
          {step === 6 ? "Finish Setup" : "Next"} <ArrowRight className="h-3.5 w-3.5" />
        </AuthButton>
      </div>

      <p className="mt-4 text-center text-[11px] text-white/45">
        You can always update these details later in your settings.
      </p>
    </AuthLayout>
  );
}
