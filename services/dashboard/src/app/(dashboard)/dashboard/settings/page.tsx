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
  Plug, PlugZap, ExternalLink, FileSpreadsheet, History, Play, Pause,
  Trash2, Edit3, RefreshCw, AlertCircle, Calendar, Clock, ChevronRight,
  X, Check, AlertTriangle, RotateCcw, Download,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  getAPIKeys, getGoogleSheetExports, getGoogleSheetHistory, getIntegrations,
  getServiceAccounts, getSettings,
  type GoogleSheetExport, type ExportHistoryEntry, type Integration,
  type ExportDataSource, type ExportFormat, type ExportSchedule,
} from "@/lib/dashboards";

export default function SettingsPage() {
  const apiKeys = useMemo(() => getAPIKeys(), []);
  const serviceAccounts = useMemo(() => getServiceAccounts(), []);
  const settings = useMemo(() => getSettings(), []);
  const integrations = useMemo(() => getIntegrations(), []);
  const sheetExports = useMemo(() => getGoogleSheetExports(), []);
  const sheetHistory = useMemo(() => getGoogleSheetHistory(), []);

  const [tab, setTab] = useState<"roles" | "api" | "service" | "system" | "notifications" | "flags" | "integrations">("roles");
  const [showNewExport, setShowNewExport] = useState(false);
  const [editingExport, setEditingExport] = useState<GoogleSheetExport | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <SettingsIcon className="h-6 w-6 text-emerald-100" />
          Settings
        </h1>
        <p className="mt-1 text-sm text-white/60">Manage roles, API keys, and system configuration.</p>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-1 border-b border-white/5">
        {([
          { id: "roles",         label: "Roles"          },
          { id: "api",           label: "API Keys"       },
          { id: "service",       label: "Service Accts"  },
          { id: "system",        label: "System"         },
          { id: "notifications", label: "Notifications"  },
          { id: "flags",         label: "Feature Flags"  },
          { id: "integrations",  label: "Integrations"   },
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

      {/* ── Integrations tab ──────────────────────────────────────── */}
      {tab === "integrations" && (
        <div className="space-y-6">
          {/* Connection state — Google Sheets */}
          {(() => {
            const gs = integrations.find((i) => i.provider === "google_sheets")!;
            return (
              <Card
                title={
                  <span className="flex items-center gap-2">
                    <FileSpreadsheet className="h-4 w-4 text-emerald-200" />
                    Google Sheets
                    {gs.status === "connected" && (
                      <span className="rounded-md border border-emerald-200/40 bg-emerald-200/10 px-2 py-0.5 text-[10px] font-medium text-emerald-100">
                        CONNECTED
                      </span>
                    )}
                  </span>
                }
                subtitle="Export emissions, forecasts, and demand data to any Google Sheet you own."
                actions={
                  gs.status === "connected" ? (
                    <div className="flex items-center gap-2">
                      <button className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/80 hover:bg-white/10">
                        <RefreshCw className="h-3 w-3" /> Reconnect
                      </button>
                      <button className="inline-flex items-center gap-1 rounded-md border border-rose-300/30 bg-rose-500/10 px-2.5 py-1 text-[11px] text-rose-200 hover:bg-rose-500/15">
                        Disconnect
                      </button>
                    </div>
                  ) : (
                    <button className="inline-flex items-center gap-1.5 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20">
                      <PlugZap className="h-3.5 w-3.5" /> Connect with Google
                    </button>
                  )
                }
                data-testid="integration-google-sheets"
              >
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-white/50">Connected account</div>
                    <div className="mt-1 text-sm text-white">{gs.connected_account ?? "—"}</div>
                    {gs.connected_at && (
                      <div className="mt-0.5 text-[11px] text-white/50">
                        since {new Date(gs.connected_at).toLocaleDateString("en-AU", { year: "numeric", month: "short", day: "numeric" })}
                      </div>
                    )}
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-white/50">Granted scopes</div>
                    <ul className="mt-1 space-y-0.5 text-[11px] text-white/70">
                      {gs.scopes?.map((s) => (
                        <li key={s} className="font-mono break-all">{s}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-white/50">Active exports</div>
                    <div className="mt-1 text-2xl font-bold text-white tabular-nums">
                      {sheetExports.filter((e) => e.enabled).length}
                      <span className="ml-1 text-sm font-normal text-white/50">/ {sheetExports.length} configured</span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-white/50">
                      Last success: {(() => {
                        const last = sheetHistory.find((h) => h.status === "success");
                        return last ? new Date(last.started_at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" }) : "—";
                      })()}
                    </div>
                  </div>
                </div>
                <div className="mt-3 rounded-lg border border-emerald-200/15 bg-emerald-200/[0.03] p-3 text-[12px] text-white/70">
                  <span className="font-medium text-emerald-100">How it works:</span> Click "Connect with Google" → grant edit access to your Drive → pick a spreadsheet. ecoLens writes new rows on the schedule you choose. Existing rows in the destination range are preserved; we only append or replace a defined range.
                </div>
              </Card>
            );
          })()}

          {/* Configured exports */}
          <Card
            title="Configured exports"
            subtitle="Where ecoLens data is being written right now."
            actions={
              <button
                onClick={() => { setEditingExport(null); setShowNewExport(true); }}
                className="inline-flex items-center gap-1 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20"
                data-testid="new-export-btn"
              >
                <Plus className="h-3.5 w-3.5" /> New export
              </button>
            }
          >
            {sheetExports.length === 0 ? (
              <p className="text-sm text-white/55">No exports yet. Click "New export" to set one up.</p>
            ) : (
              <ul className="space-y-2" data-testid="export-list">
                {sheetExports.map((e) => (
                  <li
                    key={e.id}
                    className={cn(
                      "rounded-lg border bg-white/[0.02] p-3",
                      e.enabled ? "border-white/10" : "border-white/5 opacity-60",
                    )}
                    data-testid={`export-row-${e.id}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-white">{e.name}</span>
                          <ExportStatusPill status={e.last_status} />
                          {e.enabled ? (
                            <span className="rounded-md border border-emerald-200/30 bg-emerald-200/10 px-1.5 py-0.5 text-[10px] text-emerald-100">enabled</span>
                          ) : (
                            <span className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-white/60">paused</span>
                          )}
                        </div>
                        <div className="mt-1.5 grid grid-cols-1 gap-x-4 gap-y-0.5 text-[11px] text-white/60 md:grid-cols-4">
                          <span>
                            <span className="text-white/40">Source:</span>{" "}
                            <span className="font-mono text-emerald-100">{e.data_source}</span>
                          </span>
                          <span>
                            <span className="text-white/40">Region / Period:</span>{" "}
                            <span className="text-white/85">{e.region} · {e.period}</span>
                          </span>
                          <span>
                            <span className="text-white/40">Format:</span>{" "}
                            <span className="text-white/85">{e.format}</span>
                          </span>
                          <span>
                            <span className="text-white/40">Schedule:</span>{" "}
                            <span className="text-white/85">{e.schedule}</span>
                          </span>
                        </div>
                        <div className="mt-1 text-[11px] text-white/55">
                          <FileSpreadsheet className="mr-1 inline h-3 w-3" />
                          <span className="text-white/75">{e.destination.spreadsheet_name}</span>
                          <span className="text-white/35"> › </span>
                          <span className="text-white/75">{e.destination.sheet_tab}</span>
                          <span className="text-white/35"> @ </span>
                          <span className="font-mono text-white/70">{e.destination.cell_range}</span>
                        </div>
                        <div className="mt-1 flex items-center gap-3 text-[11px] text-white/55">
                          {e.last_run_at && (
                            <span>
                              <Clock className="mr-0.5 inline h-3 w-3" />
                              last: {new Date(e.last_run_at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" })}
                              {e.last_rows_written !== undefined && ` · ${e.last_rows_written.toLocaleString()} rows`}
                            </span>
                          )}
                          {e.next_run_at && e.schedule !== "manual" && (
                            <span>
                              <Calendar className="mr-0.5 inline h-3 w-3" />
                              next: {new Date(e.next_run_at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" })}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <button
                          className="rounded-md border border-white/10 bg-white/5 p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
                          title="Run now"
                          data-testid={`run-export-${e.id}`}
                        >
                          <Play className="h-3.5 w-3.5" />
                        </button>
                        <button
                          className="rounded-md border border-white/10 bg-white/5 p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
                          title={e.enabled ? "Pause" : "Resume"}
                        >
                          {e.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                        </button>
                        <button
                          onClick={() => { setEditingExport(e); setShowNewExport(true); }}
                          className="rounded-md border border-white/10 bg-white/5 p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
                          title="Edit"
                          data-testid={`edit-export-${e.id}`}
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          className="rounded-md border border-rose-300/20 bg-rose-500/5 p-1.5 text-rose-200/80 hover:bg-rose-500/15 hover:text-rose-200"
                          title="Delete"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* History */}
          <Card title="Export history" subtitle="Most recent runs first.">
            <table className="w-full text-left text-sm" data-testid="export-history">
              <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                <tr>
                  <th className="py-2">Started</th>
                  <th className="py-2">Export</th>
                  <th className="py-2">Destination</th>
                  <th className="py-2">Status</th>
                  <th className="py-2 text-right">Rows</th>
                  <th className="py-2 text-right">Duration</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {sheetHistory.map((h) => (
                  <tr key={h.id} className="text-white/85">
                    <td className="py-2 pr-2 text-[11px] text-white/60">
                      {new Date(h.started_at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" })}
                    </td>
                    <td className="py-2 pr-2">
                      <div className="text-white">{h.export_name}</div>
                      <div className="text-[10px] text-white/45">via {h.trigger}</div>
                    </td>
                    <td className="py-2 pr-2 text-[11px] text-white/65">{h.destination}</td>
                    <td className="py-2 pr-2">
                      <HistoryStatusPill status={h.status} error={h.error} />
                    </td>
                    <td className="py-2 pr-2 text-right tabular-nums">{h.rows_written.toLocaleString()}</td>
                    <td className="py-2 pr-2 text-right tabular-nums text-[11px] text-white/60">
                      {h.duration_ms < 1000 ? `${h.duration_ms} ms` : `${(h.duration_ms / 1000).toFixed(2)} s`}
                    </td>
                    <td className="py-2 pr-2 text-right">
                      {h.status === "failed" ? (
                        <button className="inline-flex items-center gap-1 rounded-md border border-amber-300/30 bg-amber-300/10 px-2 py-0.5 text-[10px] text-amber-200 hover:bg-amber-300/15">
                          <RotateCcw className="h-3 w-3" /> Retry
                        </button>
                      ) : h.status === "success" ? (
                        <button className="rounded-md border border-white/10 bg-white/5 p-1 text-white/60 hover:bg-white/10 hover:text-white" title="Download export log">
                          <Download className="h-3 w-3" />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {/* Other integrations (placeholders) */}
          <Card title="Other integrations" subtitle="Connect ecoLens to the rest of your stack.">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {integrations
                .filter((i) => i.provider !== "google_sheets")
                .map((i) => (
                  <IntegrationCard key={i.id} integration={i} />
                ))}
            </div>
          </Card>

          {/* New / edit export modal */}
          {showNewExport && (
            <NewExportModal
              existing={editingExport}
              onClose={() => { setShowNewExport(false); setEditingExport(null); }}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Integrations — sub-components
// ───────────────────────────────────────────────────────────────────────

function ExportStatusPill({ status }: { status?: GoogleSheetExport["last_status"] }) {
  if (!status) return null;
  const map: Record<string, string> = {
    success: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
    failed:  "border-rose-300/40 bg-rose-500/10 text-rose-200",
    running: "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
    queued:  "border-amber-300/40 bg-amber-300/10 text-amber-200",
  };
  return (
    <span className={cn("rounded-md border px-1.5 py-0.5 text-[10px] font-medium", map[status])}>
      {status}
    </span>
  );
}

function HistoryStatusPill({
  status,
  error,
}: {
  status: ExportHistoryEntry["status"];
  error?: ExportHistoryEntry["error"];
}) {
  if (status === "success") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-emerald-200/40 bg-emerald-200/10 px-2 py-0.5 text-[10px] text-emerald-100">
        <Check className="h-3 w-3" /> success
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-cyan-300/40 bg-cyan-300/10 px-2 py-0.5 text-[10px] text-cyan-200">
        <RefreshCw className="h-3 w-3 animate-spin" /> running
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md border border-rose-300/40 bg-rose-500/10 px-2 py-0.5 text-[10px] text-rose-200"
        title={error ? `${error.code}: ${error.message}` : "Failed"}
      >
        <X className="h-3 w-3" /> failed
      </span>
    );
  }
  return (
    <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-white/60">
      {status}
    </span>
  );
}

function IntegrationCard({ integration: i }: { integration: Integration }) {
  const statusTone =
    i.status === "connected"  ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" :
    i.status === "error"      ? "border-rose-300/40 bg-rose-500/10 text-rose-200" :
    i.status === "expired"    ? "border-amber-300/40 bg-amber-300/10 text-amber-200" :
                                "border-white/10 bg-white/5 text-white/55";

  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        i.coming_soon ? "border-white/5 bg-white/[0.015] opacity-70" : "border-white/10 bg-white/[0.02]",
      )}
      data-testid={`integration-${i.provider}`}
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={cn("grid h-8 w-8 place-items-center rounded-lg border bg-white/[0.04]",
            i.coming_soon ? "border-white/10" : `border-${i.icon_color}/30`
          )}>
            <Plug className="h-4 w-4 text-white/60" />
          </span>
          <div>
            <div className="text-sm font-medium text-white">{i.name}</div>
            <div className="text-[10px] text-white/45">{i.category}</div>
          </div>
        </div>
        {i.coming_soon ? (
          <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-white/55">soon</span>
        ) : (
          <span className={cn("rounded-md border px-2 py-0.5 text-[10px] font-medium", statusTone)}>
            {i.status}
          </span>
        )}
      </div>
      <p className="text-[12px] text-white/65">{i.description}</p>
      <div className="mt-3 flex items-center justify-between">
        {i.coming_soon ? (
          <span className="text-[11px] text-white/45">Available in a future release</span>
        ) : i.status === "connected" ? (
          <span className="text-[11px] text-white/55">
            {i.connected_account}
          </span>
        ) : (
          <span className="text-[11px] text-white/45">Not connected</span>
        )}
        {i.coming_soon ? null : (
          <button className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/80 hover:bg-white/10">
            {i.status === "connected" ? "Manage" : "Connect"}
            <ChevronRight className="h-3 w-3" />
          </button>
        )}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// New / edit export modal
// ───────────────────────────────────────────────────────────────────────

const DATA_SOURCE_LABELS: Record<ExportDataSource, string> = {
  emissions_total:        "Emissions — Total (kgCO₂e)",
  emissions_by_region:    "Emissions — By region",
  emissions_by_source:    "Emissions — By source (coal/gas/wind/...)",
  emissions_by_scope:     "Emissions — By GHG scope (1/2/3)",
  forecast_quantiles:     "Forecast — P10/P50/P90 quantiles",
  demand_timeseries:      "Demand — Timeseries (MW)",
  renewable_mix:          "Renewable mix (% by source)",
  carbon_intensity:       "Carbon intensity (gCO₂e/kWh)",
  anomalies:              "Anomalies (last N)",
  data_quality_issues:    "Data quality issues",
  system_health:          "System health metrics",
};

function NewExportModal({
  existing,
  onClose,
}: {
  existing: GoogleSheetExport | null;
  onClose: () => void;
}) {
  const isEdit = !!existing;
  const [name, setName] = useState(existing?.name ?? "");
  const [dataSource, setDataSource] = useState<ExportDataSource>(existing?.data_source ?? "emissions_total");
  const [region, setRegion] = useState<GoogleSheetExport["region"]>(existing?.region ?? "NEM");
  const [period, setPeriod] = useState<GoogleSheetExport["period"]>(existing?.period ?? "7d");
  const [format, setFormat] = useState<ExportFormat>(existing?.format ?? "raw");
  const [schedule, setSchedule] = useState<ExportSchedule>(existing?.schedule ?? "daily");
  const [notify, setNotify] = useState(existing?.notify_on_failure ?? true);
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      data-testid="new-export-modal"
    >
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-white/10 bg-[#0a1210]"
        onClick={(ev) => ev.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/5 px-5 py-4">
          <h2 className="flex items-center gap-2 text-base font-semibold text-white">
            <FileSpreadsheet className="h-4 w-4 text-emerald-200" />
            {isEdit ? "Edit export" : "New Google Sheets export"}
          </h2>
          <button onClick={onClose} className="rounded-md p-1 text-white/60 hover:bg-white/5 hover:text-white" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <Field label="Name" hint="Internal label — shown in the export list.">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. NSW1 Daily Emissions"
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/40 focus:outline-none"
              data-testid="export-name"
            />
          </Field>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="Data source">
              <select
                value={dataSource}
                onChange={(e) => setDataSource(e.target.value as ExportDataSource)}
                className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
                data-testid="export-source"
              >
                {Object.entries(DATA_SOURCE_LABELS).map(([k, v]) => (
                  <option key={k} value={k} className="bg-[#0a1210]">{v}</option>
                ))}
              </select>
            </Field>

            <Field label="Region">
              <select
                value={region}
                onChange={(e) => setRegion(e.target.value as GoogleSheetExport["region"])}
                className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
              >
                {["NEM", "WEM", "NSW1", "QLD1", "VIC1", "SA1", "TAS1", "ALL"].map((r) => (
                  <option key={r} value={r} className="bg-[#0a1210]">{r}</option>
                ))}
              </select>
            </Field>

            <Field label="Time period">
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value as GoogleSheetExport["period"])}
                className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
              >
                {[
                  { v: "24h",  l: "Last 24 hours" },
                  { v: "7d",   l: "Last 7 days"   },
                  { v: "30d",  l: "Last 30 days"  },
                  { v: "90d",  l: "Last 90 days"  },
                  { v: "ytd",  l: "Year to date"  },
                  { v: "custom", l: "Custom range" },
                ].map((o) => (
                  <option key={o.v} value={o.v} className="bg-[#0a1210]">{o.l}</option>
                ))}
              </select>
            </Field>

            <Field label="Format">
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value as ExportFormat)}
                className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
              >
                <option value="raw"     className="bg-[#0a1210]">Raw — one row per record</option>
                <option value="summary" className="bg-[#0a1210]">Summary — one row per period</option>
                <option value="pivot"   className="bg-[#0a1210]">Pivot — region × period matrix</option>
              </select>
            </Field>

            <Field label="Schedule">
              <select
                value={schedule}
                onChange={(e) => setSchedule(e.target.value as ExportSchedule)}
                className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
              >
                <option value="manual"  className="bg-[#0a1210]">Manual only</option>
                <option value="hourly"  className="bg-[#0a1210]">Every hour</option>
                <option value="daily"   className="bg-[#0a1210]">Every day</option>
                <option value="weekly"  className="bg-[#0a1210]">Every week</option>
                <option value="monthly" className="bg-[#0a1210]">Every month</option>
              </select>
            </Field>

            <Field label="Destination">
              <button className="flex w-full items-center justify-between rounded-md border border-dashed border-white/15 bg-white/[0.02] px-3 py-1.5 text-sm text-white/70 hover:border-emerald-200/30 hover:bg-emerald-200/[0.03] hover:text-white">
                <span>Pick a Google Sheet</span>
                <ChevronRight className="h-4 w-4 text-white/40" />
              </button>
            </Field>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <ToggleRow
              label="Notify on failure"
              hint="Email the export owner if a run fails."
              checked={notify}
              onChange={setNotify}
            />
            <ToggleRow
              label="Enabled"
              hint="Pause to keep the configuration but stop scheduled runs."
              checked={enabled}
              onChange={setEnabled}
            />
          </div>

          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-[12px] text-white/70">
            <div className="mb-1 flex items-center gap-1.5 text-white/85">
              <AlertCircle className="h-3.5 w-3.5 text-amber-200" />
              <span className="font-medium">First run preview</span>
            </div>
            Once saved, ecoLens will:
            <ol className="ml-5 mt-1 list-decimal space-y-0.5 text-white/65">
              <li>Open a Google Picker and let you choose the destination workbook + tab</li>
              <li>Compute the dataset for <code className="font-mono text-emerald-100">{region}</code> / <code className="font-mono text-emerald-100">{period}</code> / <code className="font-mono text-emerald-100">{format}</code></li>
              <li>Write the first batch right away (or queue it for the next <code className="font-mono text-emerald-100">{schedule}</code> tick)</li>
              <li>Show a preview link in the history table so you can verify the format</li>
            </ol>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-white/5 px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80 hover:bg-white/10"
          >
            Cancel
          </button>
          <button
            className="inline-flex items-center gap-1.5 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20"
            data-testid="export-save"
          >
            <Check className="h-3.5 w-3.5" />
            {isEdit ? "Save changes" : "Pick destination & start"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-white/50">{label}</label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-white/40">{hint}</p>}
    </div>
  );
}

function ToggleRow({
  label, hint, checked, onChange,
}: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-white/[0.02] p-3 text-left hover:border-emerald-200/30"
    >
      <div>
        <div className="text-sm font-medium text-white">{label}</div>
        {hint && <div className="text-[11px] text-white/45">{hint}</div>}
      </div>
      <span
        className={cn(
          "grid h-5 w-9 place-items-start rounded-full p-0.5 transition-colors",
          checked ? "bg-emerald-300/40" : "bg-white/10",
        )}
      >
        <span
          className={cn(
            "h-4 w-4 rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-4" : "translate-x-0",
          )}
        />
      </span>
    </button>
  );
}
