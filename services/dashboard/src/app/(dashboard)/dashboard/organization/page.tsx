/**
 * /dashboard/organization — Org profile, locations, facilities,
 * employees, reporting frameworks.
 */
import { Building2, Edit3, MapPin, Plus } from "lucide-react";

import {
  ORG_OVERVIEW,
  ORG_LOCATIONS,
  ORG_FACILITIES,
  ORG_EMPLOYEES,
  ORG_FRAMEWORKS,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { DataTable, Pill, NameCell } from "@/components/dashboard/data-table";
import { DonutChart } from "@/components/dashboard/charts";

export const metadata = { title: "Organization — EcoLens" };

const FLAG_COLORS: Record<string, string> = {
  "🇧🇩": "rgba(132,204,22,0.95)",
  "🇸🇬": "rgba(56,189,248,0.95)",
  "🇺🇸": "rgba(168,85,247,0.95)",
  "🇬🇧": "rgba(244,63,94,0.95)",
  "🇩🇪": "rgba(245,158,11,0.95)",
};

export default function OrganizationPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Organization <span className="ml-1">🏢</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Manage your organization profile, settings, and operational details<br />to ensure accurate reporting and compliance.
          </p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80 hover:text-white">
          <Edit3 className="h-3.5 w-3.5" /> Edit Organization
        </button>
      </div>

      {/* Org Overview */}
      <Card title="Organization Overview">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
          <div className="flex items-center gap-3">
            <div className="grid h-16 w-16 place-items-center rounded-full bg-gradient-to-br from-emerald-400 to-lime-300">
              <span className="text-2xl">🌿</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold text-white">{ORG_OVERVIEW.name}</h2>
                <Pill color="emerald">✓ Verified</Pill>
              </div>
              <p className="text-sm text-white/60">Driving measurable impact towards a sustainable future.</p>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-white/50">
                <span className="flex items-center gap-1"><Building2 className="h-3 w-3" /> {ORG_OVERVIEW.industry}</span>
                <span>📅 Founded {ORG_OVERVIEW.founded}</span>
                <span>📍 {ORG_OVERVIEW.hq}</span>
                <span>🆔 {ORG_OVERVIEW.orgId}</span>
              </div>
            </div>
          </div>
        </div>
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            { label: "Employees",         value: ORG_OVERVIEW.employees, sub: `↑ ${ORG_OVERVIEW.growth}% vs last year`, icon: "👥" },
            { label: "Locations",         value: ORG_OVERVIEW.locations, sub: "Across 4 countries", icon: "📍" },
            { label: "Facilities",        value: ORG_OVERVIEW.facilities, sub: "Across 8 locations", icon: "🏢" },
            { label: "Fiscal Year",       value: ORG_OVERVIEW.fiscalYear, sub: "Calendar Year", icon: "📅" },
            { label: "Reporting Framework", value: ORG_OVERVIEW.framework, sub: "Primary Framework", icon: "📊" },
          ].map((row) => (
            <div key={row.label} className="rounded-xl border border-white/5 bg-white/[0.02] p-4 text-center">
              <p className="text-2xl">{row.icon}</p>
              <p className="mt-2 text-2xl font-bold text-white">{row.value}</p>
              <p className="text-[10px] text-white/50">{row.label}</p>
              <p className="mt-1 text-[10px] text-emerald-400">{row.sub}</p>
            </div>
          ))}
        </div>
      </Card>

      {/* Profile tabs */}
      <div className="flex items-center gap-4 border-b border-white/5">
        {["Profile", "Locations", "Employees", "Facilities", "Fiscal Year", "Reporting Framework"].map((t, i) => (
          <button
            key={t}
            className={`relative -mb-px px-3 py-2 text-sm ${i === 0 ? "text-lime-300" : "text-white/60 hover:text-white"}`}
          >
            {t}
            {i === 0 && <span className="absolute inset-x-0 -bottom-px h-0.5 bg-lime-300" />}
          </button>
        ))}
      </div>

      {/* Profile + Org Settings */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Profile">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {/* Organization Details */}
            <div>
              <h3 className="text-sm font-semibold text-white">Organization Details <Edit3 className="ml-1 inline h-3 w-3 text-white/40" /></h3>
              <div className="mt-3 space-y-3 text-xs">
                {[
                  { label: "Organization Name", value: ORG_OVERVIEW.name },
                  { label: "Legal Name",        value: "EcoLens Technologies Limited" },
                  { label: "Industry",          value: ORG_OVERVIEW.industry },
                  { label: "Sub-Industry",      value: "IT Consulting & Software Development" },
                  { label: "Website",           value: "www.ecolens.com", link: true },
                  { label: "Phone",             value: "+880 1712 345678" },
                  { label: "Email",             value: "info@ecolens.com", link: true },
                  { label: "Description",       value: "EcoLens helps organizations measure, monitor and reduce their carbon footprint with AI-powered insights and effortless reporting." },
                ].map((row) => (
                  <div key={row.label}>
                    <p className="text-[10px] text-white/50">{row.label}</p>
                    <p className={`mt-0.5 text-white ${row.link ? "text-emerald-300" : ""}`}>{row.value}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Address + Map */}
            <div>
              <h3 className="text-sm font-semibold text-white">Address <Edit3 className="ml-1 inline h-3 w-3 text-white/40" /></h3>
              <div className="mt-3 space-y-3 text-xs">
                <p className="text-white">Headquarters</p>
                <p className="text-white/70">House 12, Road 5, Dhanmondi<br />Dhaka 1205, Bangladesh</p>
                <div className="rounded-md border border-white/5 bg-white/[0.02] p-2">
                  <div className="relative aspect-[2/1] w-full">
                    <svg viewBox="0 0 100 50" className="h-full w-full">
                      <ellipse cx="50" cy="25" rx="48" ry="22" fill="rgba(255,255,255,0.04)" />
                      {[[55, 28], [52, 30], [48, 25], [60, 20], [40, 22], [70, 18], [30, 30]].map(([x, y], i) => (
                        <circle key={i} cx={x} cy={y} r="0.6" fill="rgba(132,204,22,0.7)" />
                      ))}
                      <circle cx="65" cy="28" r="2" fill="rgba(132,204,22,0.95)" />
                      <circle cx="65" cy="28" r="3" fill="none" stroke="rgba(132,204,22,0.4)" />
                    </svg>
                  </div>
                </div>
                <p className="text-[10px] text-white/50">Time Zone</p>
                <p className="text-white">Asia/Dhaka (GMT+6)</p>
                <p className="text-[10px] text-white/50">Currency</p>
                <p className="text-white">USD – US Dollar</p>
              </div>
            </div>
          </div>
        </Card>

        <Card title="Organization Settings" actions={<Edit3 className="h-3.5 w-3.5 text-white/40" />}>
          <div className="space-y-3 text-xs">
            {[
              { label: "Industry Classification", value: "SIC 7372, NAICS 541511" },
              { label: "Organization Type",        value: "Private Company" },
              { label: "Fiscal Year",              value: "Calendar Year (Jan – Dec)" },
              { label: "Default Reporting Currency", value: "USD – US Dollar" },
              { label: "Base Year",                value: "2022" },
              { label: "Data Retention Policy",    value: "7 Years" },
              { label: "Organization Logo",        value: "✓" },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between border-b border-white/5 py-2 last:border-b-0">
                <span className="text-white/60">{row.label}</span>
                <span className="text-white">{row.value}</span>
              </div>
            ))}
            <div className="mt-3 flex items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] p-3">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-gradient-to-br from-emerald-400 to-lime-300 text-xl">🌿</span>
              <span className="text-lg font-bold text-white">EcoLens</span>
            </div>
          </div>
        </Card>
      </div>

      {/* Locations + Facilities + Employees */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          title="Locations"
          actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}
        >
          <div className="space-y-2">
            {ORG_LOCATIONS.map((l) => (
              <div key={l.id} className="flex items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                <span className="text-xl">{l.flag}</span>
                <div className="flex-1">
                  <p className="text-sm font-semibold text-white">{l.name}</p>
                  <Pill color={l.type === "Headquarters" ? "emerald" : l.type === "Regional Office" ? "sky" : "lime"} className="mt-0.5">{l.type}</Pill>
                </div>
                <p className="text-sm font-semibold text-white">{l.employees}</p>
              </div>
            ))}
            <p className="flex items-center gap-1 text-xs text-emerald-300">
              <Plus className="h-3 w-3" /> 3 more locations
            </p>
          </div>
        </Card>

        <Card
          title="Facilities"
          actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}
        >
          <div className="space-y-3">
            {ORG_FACILITIES.map((f) => (
              <div key={f.id} className="flex items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-400/10 text-emerald-300">
                  <Building2 className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-white">{f.name}</p>
                  <p className="text-xs text-white/50">{f.location}</p>
                  <p className="mt-0.5 text-xs text-white/70">Floor Area: {f.area}</p>
                </div>
              </div>
            ))}
            <p className="flex items-center gap-1 text-xs text-emerald-300">
              <Plus className="h-3 w-3" /> 10 more facilities
            </p>
          </div>
        </Card>

        <Card
          title="Employees"
          actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}
        >
          <div className="flex flex-col items-center">
            <DonutChart
              data={ORG_EMPLOYEES.breakdown.map((b) => ({ label: b.label, value: b.value, color: b.color }))}
              size={150}
              thickness={18}
              centerLabel={`${ORG_EMPLOYEES.total}`}
              centerSub="Total"
            />
            <div className="mt-4 w-full space-y-1.5 text-xs">
              {ORG_EMPLOYEES.breakdown.map((b) => (
                <div key={b.label} className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-white/70">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: b.color }} />
                    {b.label}
                  </span>
                  <span className="text-white">{b.value} ({b.percent}%)</span>
                </div>
              ))}
            </div>
            <button className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-400/10">
              Manage Employees →
            </button>
          </div>
        </Card>
      </div>

      {/* Reporting Framework */}
      <Card
        title="Reporting Framework"
        subtitle="Manage your reporting frameworks and disclosure standards for compliance and transparency."
        actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">Manage Frameworks →</button>}
      >
        <p className="mb-3 text-xs text-white/50">Primary Framework</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {ORG_FRAMEWORKS.map((f) => (
            <div key={f.id} className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
              <div className="flex items-center gap-2">
                <span className={`grid h-9 w-9 place-items-center rounded-full text-white ${f.primary ? "bg-emerald-400/20" : "bg-white/5"}`}>
                  🌿
                </span>
                <div className="flex-1">
                  <p className="text-sm font-semibold text-white">{f.name}</p>
                  <p className="text-[10px] text-white/50">{f.sub}</p>
                </div>
              </div>
              <Pill color={f.primary ? "emerald" : f.role === "Supporting" ? "gray" : "lime"} className="mt-3">
                {f.role}
              </Pill>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
