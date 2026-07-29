/**
 * /dashboard/settings — Settings & Users (Administrators)
 *
 * Combines:
 *   - User management (Users, Roles, API Keys, Service Accounts)
 *   - System configuration (General, Branding, Security, Env, Storage, Feature Flags)
 *   - Notification preferences
 */
"use client";

import { useMemo, useState } from "react";
import {
  CheckCircle2, ChevronDown, ChevronUp, Crown, Eye, Filter, KeyRound,
  Mail, Search, Settings as SettingsIcon, Shield, ShieldCheck,
  User as UserIcon, XCircle, BellRing, Cpu, Database, Plus, Sliders,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  getAPIKeys, getOrganizations, getServiceAccounts, getSettings, getUsers, type UserRole,
} from "@/lib/dashboards";

const ROLE_TONE: Record<UserRole, string> = {
  admin:   "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
  analyst: "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
  viewer:  "border-white/10 bg-white/5 text-white/60",
  owner:   "border-amber-300/40 bg-amber-300/10 text-amber-200",
};
const STATUS_TONE: Record<string, string> = {
  active:    "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
  invited:   "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
  suspended: "border-rose-300/40 bg-rose-300/10 text-rose-200",
};

export default function SettingsPage() {
  const users = useMemo(() => getUsers(), []);
  const orgs = useMemo(() => getOrganizations(), []);
  const apiKeys = useMemo(() => getAPIKeys(), []);
  const serviceAccounts = useMemo(() => getServiceAccounts(), []);
  const settings = useMemo(() => getSettings(), []);

  const [tab, setTab] = useState<"users" | "roles" | "api" | "service" | "system" | "notifications" | "flags">("users");
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<UserRole | "all">("all");

  const filteredUsers = users.filter((u) => {
    if (search && !`${u.name} ${u.email}`.toLowerCase().includes(search.toLowerCase())) return false;
    if (roleFilter !== "all" && u.role !== roleFilter) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <SettingsIcon className="h-6 w-6 text-emerald-100" />
          Settings &amp; Users
        </h1>
        <p className="mt-1 text-sm text-white/60">Manage users, roles, API keys, and system configuration.</p>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-1 border-b border-white/5">
        {([
          { id: "users",         label: "Users"          },
          { id: "roles",         label: "Roles"          },
          { id: "api",           label: "API Keys"       },
          { id: "service",       label: "Service Accts"  },
          { id: "system",        label: "System"         },
          { id: "notifications", label: "Notifications"  },
          { id: "flags",         label: "Feature Flags"  },
        ] as const).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
              tab === t.id ? "border-emerald-200 text-emerald-100" : "border-transparent text-white/60 hover:text-white",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "users" && (
        <Card>
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
                <input
                  type="text"
                  placeholder="Search users…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="rounded-md border border-white/10 bg-white/[0.04] py-1.5 pl-7 pr-3 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
                />
              </div>
              <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] p-1 text-xs">
                {(["all", "admin", "analyst", "viewer"] as const).map((r) => (
                  <button
                    key={r}
                    onClick={() => setRoleFilter(r as UserRole | "all")}
                    className={cn("rounded px-2 py-0.5",
                      roleFilter === r ? "bg-emerald-200/15 text-emerald-100" : "text-white/60 hover:text-white"
                    )}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <button className="inline-flex items-center gap-1 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20">
              <Plus className="h-3.5 w-3.5" /> Invite User
            </button>
          </div>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
              <tr>
                <th className="py-2">User</th>
                <th className="py-2">Role</th>
                <th className="py-2">Org</th>
                <th className="py-2">MFA</th>
                <th className="py-2">Last Active</th>
                <th className="py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {filteredUsers.map((u) => (
                <tr key={u.id} className="text-white/85">
                  <td className="py-2 pr-2">
                    <div className="font-medium">{u.name}</div>
                    <div className="text-[11px] text-white/50">{u.email}</div>
                  </td>
                  <td className="py-2 pr-2">
                    <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", ROLE_TONE[u.role])}>{u.role}</span>
                  </td>
                  <td className="py-2 pr-2 text-white/60">{u.org}</td>
                  <td className="py-2 pr-2">
                    {u.mfa_enabled ? <CheckCircle2 className="h-4 w-4 text-emerald-200" /> : <XCircle className="h-4 w-4 text-white/30" />}
                  </td>
                  <td className="py-2 pr-2 text-white/60">{u.last_active}</td>
                  <td className="py-2 pr-2">
                    <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                      STATUS_TONE[u.status] ?? "border-white/10 bg-white/5 text-white/60"
                    )}>{u.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === "roles" && (
        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">Roles &amp; Permissions</h2>
          <ul className="space-y-1.5 text-sm">
            {[
              { name: "Owner",   desc: "Full control including billing, all-org management",          users: 1, perms: ["*"] },
              { name: "Admin",   desc: "Manage users, models, pipelines, settings, system health",  users: 2, perms: ["read:*", "write:*"] },
              { name: "Analyst", desc: "Read all data, run models, export reports",                users: 2, perms: ["read:*", "write:reports"] },
              { name: "Viewer",  desc: "Read-only access to dashboards and reports",               users: 2, perms: ["read:dashboards"] },
            ].map((r) => (
              <li key={r.name} className="rounded-md border border-white/5 bg-white/[0.02] p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-white/85 font-medium">{r.name}</div>
                    <div className="text-[11px] text-white/50">{r.desc}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-emerald-100">{r.users} users</div>
                    <div className="text-[11px] text-white/50 font-mono">{r.perms.join(", ")}</div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {tab === "api" && (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">API Keys</h2>
            <button className="inline-flex items-center gap-1 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20">
              <Plus className="h-3.5 w-3.5" /> Create Key
            </button>
          </div>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
              <tr><th className="py-2">Name</th><th className="py-2">Key</th><th className="py-2">Created</th><th className="py-2">Last Used</th><th className="py-2">Scopes</th></tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {apiKeys.map((k) => (
                <tr key={k.id} className="text-white/85">
                  <td className="py-2 pr-2">{k.name}</td>
                  <td className="py-2 pr-2 font-mono text-[11px] text-emerald-100">{k.prefix}</td>
                  <td className="py-2 pr-2 text-white/60">{k.created_at}</td>
                  <td className="py-2 pr-2 text-white/60">{k.last_used}</td>
                  <td className="py-2 pr-2 text-[11px] text-white/60">{k.scopes.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === "service" && (
        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">Service Accounts</h2>
          <ul className="space-y-1.5 text-sm">
            {serviceAccounts.map((s) => (
              <li key={s.id} className="rounded-md border border-white/5 bg-white/[0.02] p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-white/85 font-medium">{s.name}</div>
                    <div className="text-[11px] text-white/50 font-mono">{s.client_id} · {s.purpose}</div>
                  </div>
                  <div className="flex items-center gap-2 text-[11px]">
                    <span className="text-white/50">created {s.created_at}</span>
                    <span className={cn("rounded-md border px-2 py-0.5 font-medium",
                      s.enabled ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" : "border-white/10 bg-white/5 text-white/60"
                    )}>{s.enabled ? "enabled" : "disabled"}</span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {tab === "system" && (
        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">System Configuration</h2>
          <div className="space-y-3">
            {(["general", "branding", "security", "env", "secrets", "storage", "backup"] as const).map((cat) => (
              <div key={cat}>
                <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-white/50">{cat}</h3>
                <div className="space-y-1.5">
                  {settings.filter((s) => s.category === cat).map((s) => (
                    <div key={s.key} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                      <div>
                        <div className="text-sm text-white/85">{s.label}</div>
                        <div className="text-[11px] text-white/50 font-mono">{s.key}</div>
                      </div>
                      <div>
                        {s.type === "boolean" ? (
                          <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                            s.value ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" : "border-white/10 bg-white/5 text-white/60"
                          )}>{String(s.value)}</span>
                        ) : (
                          <code className="rounded bg-black/30 px-1.5 py-0.5 font-mono text-[11px] text-emerald-100">{String(s.value)}</code>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === "notifications" && (
        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">Notification Preferences</h2>
          <ul className="space-y-1.5 text-sm">
            {[
              { name: "Email — Recommendations",   enabled: true  },
              { name: "Email — Forecasts ready",   enabled: true  },
              { name: "Email — Weekly report",     enabled: true  },
              { name: "Slack — Data Quality",      enabled: true  },
              { name: "Slack — Pipeline failures", enabled: true  },
              { name: "Webhook — Outbound",        enabled: false },
              { name: "Push — Mobile app",         enabled: false },
            ].map((n) => (
              <li key={n.name} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                <span className="text-white/85">{n.name}</span>
                <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                  n.enabled ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" : "border-white/10 bg-white/5 text-white/60"
                )}>{n.enabled ? "on" : "off"}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {tab === "flags" && (
        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">Feature Flags</h2>
          <ul className="space-y-1.5 text-sm">
            {settings.filter((s) => s.category === "flags").map((f) => (
              <li key={f.key} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                <div>
                  <div className="text-white/85">{f.label}</div>
                  <div className="text-[11px] text-white/50 font-mono">{f.key}</div>
                </div>
                <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                  f.value ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" : "border-white/10 bg-white/5 text-white/60"
                )}>{String(f.value)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Always show org summary at bottom */}
      <Card>
        <h2 className="mb-3 text-base font-semibold text-white">Organizations</h2>
        <ul className="space-y-1.5 text-sm">
          {orgs.map((o) => (
            <li key={o.id} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
              <div>
                <div className="text-white/85 font-medium">{o.name}</div>
                <div className="text-[11px] text-white/50">{o.industry} · {o.region} · {o.members} members · since {o.created_at}</div>
              </div>
              <div className="text-right">
                <div className="text-emerald-100 tabular-nums">{o.emissions_tco2e.toLocaleString()} tCO₂e</div>
                <div className="text-[11px] text-white/50">{o.plan}</div>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
