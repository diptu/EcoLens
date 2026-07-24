"use client";

import { useState } from "react";

const TABS = ["Overview", "Emissions Trends", "Benchmarking", "Industry Comparison", "Regional Comparison", "Emission Intensity", "Cost vs. Emissions", "Opportunities"] as const;

export function AnalyticsTabs() {
  const [tab, setTab] = useState<typeof TABS[number]>("Overview");
  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-white/5">
      {TABS.map((t) => (
        <button
          key={t}
          onClick={() => setTab(t)}
          className={`relative -mb-px px-3 py-2 text-sm transition-colors ${
            tab === t ? "text-lime-300" : "text-white/60 hover:text-white"
          }`}
        >
          {t}
          {tab === t && <span className="absolute inset-x-0 -bottom-px h-0.5 bg-lime-300" />}
        </button>
      ))}
    </div>
  );
}
