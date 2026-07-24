/**
 * /dashboard/profile — Personal information, preferences, security,
 * notifications, account settings. Left rail with section nav.
 */
import { Camera, Edit3, KeyRound, LogOut, Trash2, Upload } from "lucide-react";

import {
  PROFILE_USER,
  PROFILE_PREFERENCES,
  PROFILE_NOTIFICATION_CATEGORIES,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";

export const metadata = { title: "Profile — EcoLens" };

const SECTIONS = [
  { label: "Personal Information", icon: "👤", active: true },
  { label: "Preferences",           icon: "🎛️" },
  { label: "Password & Security",   icon: "🔒" },
  { label: "Notifications",         icon: "🔔" },
  { label: "Account Settings",      icon: "⚙️" },
  { label: "Sessions & Devices",    icon: "💻" },
  { label: "API Keys",              icon: "🔑" },
];

export default function ProfilePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white md:text-3xl">Profile</h1>
        <p className="mt-1 text-sm text-white/60 max-w-2xl">
          Manage your personal information, preferences, and account settings.
        </p>
      </div>

      {/* Profile header */}
      <Card>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="flex items-center gap-4">
            <div className="relative grid h-20 w-20 place-items-center overflow-hidden rounded-full bg-gradient-to-br from-emerald-400 to-lime-300 text-2xl font-bold text-black">
              D
              <button className="absolute bottom-0 right-0 grid h-6 w-6 place-items-center rounded-full border-2 border-[#0a1410] bg-white/10 text-white hover:bg-white/20">
                <Camera className="h-3 w-3" />
              </button>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold text-white">{PROFILE_USER.name}</h2>
                <Pill color="emerald">Admin</Pill>
              </div>
              <p className="text-xs text-white/60">{PROFILE_USER.email}</p>
              <p className="mt-2 text-xs text-white/70 max-w-xs">{PROFILE_USER.bio}</p>
            </div>
          </div>
          <div className="space-y-1.5 text-xs">
            {[
              { label: "Role",          value: PROFILE_USER.role,        icon: "👤" },
              { label: "Department",    value: PROFILE_USER.department,  icon: "🏢" },
              { label: "Location",      value: PROFILE_USER.location,    icon: "📍" },
              { label: "Member since",  value: PROFILE_USER.memberSince, icon: "📅" },
              { label: "Last login",    value: PROFILE_USER.lastLogin,   icon: "🕒" },
            ].map((row) => (
              <div key={row.label} className="flex items-center gap-2 text-white/70">
                <span>{row.icon}</span>
                <span className="text-white/50 w-28">{row.label}</span>
                <span className="text-white">{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Section nav */}
        <Card>
          <ul className="space-y-1">
            {SECTIONS.map((s) => (
              <li key={s.label}>
                <button
                  className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm ${
                    s.active ? "border-l-2 border-emerald-400 bg-emerald-400/5 text-white" : "text-white/70 hover:bg-white/5"
                  }`}
                >
                  <span>{s.icon}</span> {s.label}
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="space-y-5 lg:col-span-2">
          {/* Personal Information */}
          <Card
            title="Personal Information"
            subtitle="Update your personal details and how others see you."
            actions={
              <button className="inline-flex items-center gap-1.5 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-400/10">
                <Edit3 className="h-3.5 w-3.5" /> Edit
              </button>
            }
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {[
                { label: "Full Name",    value: PROFILE_USER.name,  type: "input" },
                { label: "Email Address", value: PROFILE_USER.email, type: "input" },
                { label: "Job Title",    value: PROFILE_USER.jobTitle, type: "input" },
                { label: "Phone Number", value: PROFILE_USER.phone,    type: "input" },
                { label: "Location",     value: PROFILE_USER.location, type: "input" },
                { label: "Language",     value: PROFILE_USER.language, type: "select" },
              ].map((row) => (
                <div key={row.label}>
                  <p className="text-xs text-white/50">{row.label}</p>
                  <p className="mt-1 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white">{row.value} {row.type === "select" && <span className="float-right text-white/40">▾</span>}</p>
                </div>
              ))}
            </div>
          </Card>

          {/* Preferences */}
          <Card
            title="Preferences"
            subtitle="Customize your experience on EcoLens."
          >
            <div className="space-y-3">
              {PROFILE_PREFERENCES.map((p) => (
                <div key={p.id} className="flex items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] p-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-white/5 text-white/60">
                    {p.id === "theme" ? "🎨" : p.id === "date" ? "📅" : p.id === "tz" ? "🕒" : p.id === "dash" ? "📊" : p.id === "units" ? "📏" : "#"}
                  </span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-white">{p.label}</p>
                    <p className="text-[10px] text-white/50">{p.hint}</p>
                  </div>
                  <button className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80 min-w-[160px] text-left">
                    {p.value} <span className="float-right text-white/40">▾</span>
                  </button>
                </div>
              ))}
            </div>
          </Card>

          {/* Password & Security */}
          <Card title="Password & Security" subtitle="Keep your account secure.">
            <div className="space-y-2">
              {[
                { label: "Password",                hint: "Last changed on Apr 18, 2024", cta: "Change Password", color: "emerald" },
                { label: "Two-Factor Authentication", hint: "Add an extra layer of security to your account", cta: "Enabled", color: "lime" },
                { label: "Login Alerts",            hint: "Get notified of new logins to your account", cta: "Enabled", color: "lime" },
                { label: "Recovery Email",          hint: "Manage your account recovery email", cta: "diptu.alam@gmail.com", color: "gray" },
              ].map((row) => (
                <button
                  key={row.label}
                  className="flex w-full items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] p-3 text-left transition-colors hover:bg-white/5"
                >
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-400/10 text-emerald-300">
                    {row.label === "Password" ? <KeyRound className="h-4 w-4" /> : "🛡️"}
                  </span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-white">{row.label}</p>
                    <p className="text-[10px] text-white/50">{row.hint}</p>
                  </div>
                  <span className="text-xs font-medium text-emerald-300">›</span>
                </button>
              ))}
            </div>
          </Card>

          {/* Notifications */}
          <Card
            title="Notifications"
            subtitle="Choose how you want to receive notifications."
            actions={
              <button className="text-xs text-emerald-300 hover:text-emerald-200">Manage All →</button>
            }
            noPadding
          >
            <div className="grid grid-cols-4 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
              <span className="col-span-2">Category</span>
              <span>In-app / Email / SMS</span>
            </div>
            <div className="divide-y divide-white/5">
              {PROFILE_NOTIFICATION_CATEGORIES.map((c) => (
                <div key={c.id} className="grid grid-cols-4 items-center gap-2 px-5 py-3">
                  <div className="col-span-2 flex items-center gap-3">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-400/10 text-base">
                      {c.id === "recs" ? "🤖" : c.id === "goals" ? "🎯" : c.id === "alerts" ? "⚠️" : c.id === "reports" ? "📄" : c.id === "compliance" ? "✅" : "📢"}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-white">{c.label}</p>
                      <p className="text-[10px] text-white/50">{c.body}</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-around text-xs text-white/60">
                    <Toggle on />
                    <Toggle on />
                    <Toggle on={c.id === "alerts" || c.id === "compliance"} />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Account Settings */}
          <Card title="Account Settings" subtitle="Manage your account and data.">
            <div className="space-y-2">
              {[
                { label: "Export My Data",     hint: "Download a copy of your personal data",                cta: "Export Data",  color: "lime",   icon: <Upload className="h-4 w-4" /> },
                { label: "Delete Account",     hint: "Permanently delete your account and all data",      cta: "Delete Account", color: "rose", icon: <Trash2 className="h-4 w-4" /> },
                { label: "Deactivate Account",  hint: "Temporarily deactivate your account",                cta: "Deactivate",    color: "amber",  icon: <LogOut className="h-4 w-4" /> },
              ].map((row) => (
                <button
                  key={row.label}
                  className="flex w-full items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] p-3 text-left transition-colors hover:bg-white/5"
                >
                  <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-md ${row.color === "rose" ? "bg-rose-400/10 text-rose-300" : row.color === "amber" ? "bg-amber-400/10 text-amber-300" : "bg-emerald-400/10 text-emerald-300"}`}>
                    {row.icon}
                  </span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-white">{row.label}</p>
                    <p className="text-[10px] text-white/50">{row.hint}</p>
                  </div>
                  <span className="text-xs font-medium text-emerald-300">{row.cta}</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Pill({ children, color }: { children: React.ReactNode; color: "emerald" | "lime" }) {
  const c = color === "emerald" ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300" : "border-lime-400/30 bg-lime-400/10 text-lime-300";
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${c}`}>{children}</span>;
}

function Toggle({ on }: { on: boolean }) {
  return (
    <div className={`relative h-5 w-9 rounded-full transition-colors ${on ? "bg-lime-300" : "bg-white/10"}`}>
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </div>
  );
}
