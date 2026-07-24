/**
 * /dashboard/notifications — Notification feed + preferences.
 */
import { Bell, Calendar, Filter, MoreHorizontal } from "lucide-react";

import {
  NOTIFICATIONS_KPIS,
  NOTIFICATION_LIST,
  NOTIFICATION_TYPES_BREAKDOWN,
  NOTIFICATION_CHANNELS,
  PROFILE_NOTIFICATION_CATEGORIES,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { DataTable, Pill, NameCell, ActionsMenu } from "@/components/dashboard/data-table";
import { DonutChart } from "@/components/dashboard/charts";

export const metadata = { title: "Notifications — EcoLens" };

const ICON_BG: Record<string, string> = {
  blue:    "rgba(56,189,248,0.15)",
  emerald: "rgba(16,185,129,0.15)",
  rose:    "rgba(244,63,94,0.15)",
  amber:   "rgba(245,158,11,0.15)",
  sky:     "rgba(56,189,248,0.15)",
  purple:  "rgba(168,85,247,0.15)",
};
const ICON_FG: Record<string, string> = {
  blue:    "text-sky-300",
  emerald: "text-emerald-300",
  rose:    "text-rose-300",
  amber:   "text-amber-300",
  sky:     "text-sky-300",
  purple:  "text-purple-300",
};
const TYPE_ICON: Record<string, string> = {
  Recommendation: "🤖",
  Goal: "🎯",
  Data: "📊",
  Report: "📄",
  Anomaly: "⚠️",
  Compliance: "✅",
  Mention: "💬",
};
const PRIORITY_COLOR = { High: "rose", Medium: "amber", Low: "lime" } as const;

export default function NotificationsPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Notifications <span className="ml-1">🔔</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Stay updated with important alerts and activities across your organization.
          </p>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {NOTIFICATIONS_KPIS.map((k) => (
          <KpiCard
            key={k.id}
            label={k.label}
            value={k.value}
            sub={k.sub}
            trend={k.id === "today" ? { direction: "up", text: "20% vs yesterday", goodWhen: "down" } : undefined}
          />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Notification list */}
        <Card
          className="lg:col-span-2"
          title="Notifications"
          actions={
            <div className="flex items-center gap-2">
              <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">All Types ▾</button>
              <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">All Channels ▾</button>
              <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
                <Filter className="h-3 w-3" />
              </button>
            </div>
          }
          noPadding
        >
          <div className="flex items-center gap-4 border-b border-white/5 px-5 py-2.5 text-xs">
            {["All", "Unread", "Mentions", "Critical"].map((tab, i) => (
              <button
                key={tab}
                className={`relative pb-1 ${i === 0 ? "text-lime-300" : "text-white/60 hover:text-white"}`}
              >
                {tab}
                {i === 0 && <span className="absolute inset-x-0 -bottom-0.5 h-0.5 bg-lime-300" />}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-4 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
            <span className="col-span-2">Notification</span>
            <span>Type</span>
            <span className="text-right">Priority / Time</span>
          </div>
          <div className="divide-y divide-white/5">
            {NOTIFICATION_LIST.map((row) => (
              <div key={row.id} className="grid grid-cols-4 items-center gap-3 px-5 py-3.5 hover:bg-white/[0.02]">
                <div className="col-span-2 flex items-start gap-3">
                  <input type="checkbox" className="mt-1.5 h-3.5 w-3.5 rounded border-white/20 bg-white/5" />
                  <span
                    className={`grid h-8 w-8 shrink-0 place-items-center rounded-md ${ICON_BG[row.color]} ${ICON_FG[row.color]}`}
                  >
                    {TYPE_ICON[row.type] ?? "🔔"}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-white">{row.title}</p>
                    <p className="mt-0.5 text-xs text-white/60">{row.body}</p>
                  </div>
                </div>
                <Pill color={
                  row.type === "Recommendation" ? "sky" :
                  row.type === "Goal" ? "emerald" :
                  row.type === "Data" ? "rose" :
                  row.type === "Report" ? "purple" :
                  row.type === "Anomaly" ? "amber" :
                  row.type === "Compliance" ? "lime" : "gray"
                }>{row.type}</Pill>
                <div className="flex items-center justify-end gap-2">
                  <Pill color={PRIORITY_COLOR[row.priority as keyof typeof PRIORITY_COLOR]}>{row.priority}</Pill>
                  <span className="text-[10px] text-white/50">{row.time}</span>
                  <ActionsMenu />
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-white/5 px-5 py-3 text-xs text-white/50">
            <span>Showing 1 to 10 of 38 notifications</span>
            <div className="flex items-center gap-1">
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">‹</button>
              {["1", "2", "3", "4"].map((p) => (
                <button key={p} className={`grid h-7 w-7 place-items-center rounded border ${p === "1" ? "border-lime-300 bg-lime-300 text-black" : "border-white/10 bg-white/5 text-white/60"}`}>{p}</button>
              ))}
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">›</button>
            </div>
          </div>
        </Card>

        <div className="space-y-5">
          <Card title="Notification Types" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}>
            <div className="space-y-2">
              {NOTIFICATION_TYPES_BREAKDOWN.map((t) => (
                <div key={t.label} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 text-white/70">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: t.color }} />
                    {t.label}
                  </span>
                  <span className="text-white">{t.value} <span className="text-white/40">({t.percent}%)</span></span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Priority Breakdown" noPadding>
            <div className="flex flex-col items-center p-5">
              <DonutChart
                data={[
                  { label: "High",   value: 6,  color: "rgba(244,63,94,0.95)" },
                  { label: "Medium", value: 16, color: "rgba(245,158,11,0.95)" },
                  { label: "Low",    value: 16, color: "rgba(132,204,22,0.95)" },
                ]}
                size={150}
                thickness={18}
                centerLabel="38"
                centerSub="Total"
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                <div className="flex items-center justify-between"><span className="flex items-center gap-2 text-white/70"><span className="h-2 w-2 rounded-full bg-rose-400" />High</span><span className="text-white">6 (16%)</span></div>
                <div className="flex items-center justify-between"><span className="flex items-center gap-2 text-white/70"><span className="h-2 w-2 rounded-full bg-amber-400" />Medium</span><span className="text-white">16 (42%)</span></div>
                <div className="flex items-center justify-between"><span className="flex items-center gap-2 text-white/70"><span className="h-2 w-2 rounded-full bg-lime-400" />Low</span><span className="text-white">16 (42%)</span></div>
              </div>
            </div>
          </Card>

          <Card title="Notification Channels" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">Manage →</button>}>
            <div className="space-y-2.5">
              {NOTIFICATION_CHANNELS.map((c) => (
                <div key={c.label} className="flex items-center justify-between text-xs">
                  <span className="text-white/70">{c.label}</span>
                  <Pill color={c.enabled ? "emerald" : "gray"}>{c.enabled ? "Enabled" : "Disabled"}</Pill>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Quiet Hours" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">Edit →</button>}>
            <p className="text-xs text-white/60">You won&apos;t receive non-critical notifications during these hours.</p>
            <div className="mt-3 space-y-1.5 text-xs">
              <p className="text-white">10:00 PM – 7:00 AM <span className="text-white/40">(Daily)</span></p>
              <p className="text-amber-300">04:30 PM <span className="text-white/40">(Critical notifications will still be delivered.)</span></p>
            </div>
          </Card>

          <Card title="Recent Activity" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}>
            <div className="space-y-3">
              {[
                { text: "All notifications marked as read", time: "May 12, 2024 9:30 AM" },
                { text: "Email notifications enabled", time: "May 10, 2024 2:15 PM" },
                { text: "Slack connected", time: "May 8, 2024 11:20 AM" },
                { text: "Quiet hours updated", time: "May 5, 2024 10:00 PM" },
              ].map((a) => (
                <p key={a.text} className="flex items-start gap-2 text-xs text-white/70">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                  <span>
                    {a.text}
                    <span className="block text-[10px] text-white/40">{a.time}</span>
                  </span>
                </p>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Notification Preferences */}
      <Card
        title="Notification Preferences"
        subtitle="Manage what you want to be notified about."
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {PROFILE_NOTIFICATION_CATEGORIES.map((c) => (
            <div key={c.id} className="flex items-start gap-3 rounded-xl border border-white/5 bg-white/[0.02] p-4">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-emerald-400/10 text-emerald-300">
                {c.id === "recs" ? "🤖" : c.id === "goals" ? "🎯" : c.id === "alerts" ? "⚠️" : c.id === "reports" ? "📄" : c.id === "compliance" ? "✅" : "🔔"}
              </span>
              <div className="flex-1">
                <p className="text-sm font-semibold text-white">{c.label}</p>
                <p className="mt-0.5 text-xs text-white/60">{c.body}</p>
              </div>
              <div className="relative h-5 w-9 shrink-0 rounded-full bg-lime-300">
                <span className="absolute right-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow" />
              </div>
            </div>
          ))}
        </div>
        <p className="mt-4 flex items-center justify-between text-xs text-white/50">
          <span>You can customize these preferences further in your account settings.</span>
          <button className="text-emerald-300 hover:text-emerald-200">Go to Settings →</button>
        </p>
      </Card>
    </div>
  );
}
