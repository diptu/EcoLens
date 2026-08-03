/**
 * /dashboard/reports — Reports management.
 *
 * Features:
 *  - KPIs, framework breakdown, popular metrics, audit trail
 *  - "New Report" dropdown (template or custom) + full creation modal
 *  - Report template cards (click to start with that template)
 *  - Schedules section
 *  - Recent reports table with quick actions (preview, download, delete)
 *  - Report preview modal
 *  - localStorage persistence for new reports + schedules
 *  - Framer Motion animations on every chart, card, and modal
 *  - Hover details on charts
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  Calendar, ChevronDown, Clock, FileText, Plus, Sparkles,
  Eye, Download, Trash2, X, Check, Copy, Mail, Globe, Lock,
  FileDown, FileSpreadsheet, FileText as FilePdf, Search, Filter,
} from "lucide-react";

import {
  REPORTS_KPIS, REPORT_TYPES, RECENT_REPORTS,
  REPORT_FRAMEWORK_BREAKDOWN, REPORT_METRICS_POPULARITY,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { Pill, NameCell, ActionsMenu } from "@/components/dashboard/data-table";
import { DonutChart, BarChart } from "@/components/dashboard/charts";
import { DetailModal } from "@/components/dashboard/detail-modal";

const TYPE_ICON: Record<string, string> = {
  ghg:   "🌿",
  scope: "📊",
  esg:   "🌍",
  cdp:   "📋",
  tcfd:  "💼",
  csrd:  "🌱",
  custom:"🛠️",
  audit: "🔒",
};

const FRAMEWORK_COLORS: Record<string, string> = {
  ESG:            "rgba(16,185,129,0.95)",
  "GHG Protocol": "rgba(132,204,22,0.95)",
  "Scope 1/2/3":  "rgba(56,189,248,0.95)",
  CDP:            "rgba(244,63,94,0.95)",
  TCFD:           "rgba(168,85,247,0.95)",
  CSRD:           "rgba(245,158,11,0.95)",
  Custom:         "rgba(148,163,184,0.6)",
  "Audit Package":"rgba(245,158,11,0.95)",
};

type ReportFormat = "PDF" | "Excel" | "CSV";
type ScheduleFrequency = "Once" | "Daily" | "Weekly" | "Monthly" | "Quarterly" | "Yearly";

interface NewReportForm {
  name: string;
  framework: string;
  periodStart: string;
  periodEnd: string;
  sites: string[];
  scopes: ("Scope 1" | "Scope 2" | "Scope 3")[];
  format: ReportFormat;
  schedule: ScheduleFrequency;
  recipients: string;
  notes: string;
  includeCharts: boolean;
  includeRawData: boolean;
  signOff: boolean;
}

interface SavedReport {
  id: string;
  name: string;
  framework: string;
  period: string;
  generated: string;
  size: string;
  status: "Completed" | "Pending" | "Failed";
  format: ReportFormat;
  schedule?: ScheduleFrequency;
  notes?: string;
  createdAt: number;
}

const SITES = [
  "All sites",
  "Sydney HQ",
  "Melbourne Plant",
  "Brisbane DC",
  "Perth Office",
  "Adelaide Lab",
];

const STORAGE_KEY = "ecolens:reports:saved";

const initialForm: NewReportForm = {
  name: "",
  framework: "GHG Protocol",
  periodStart: "2024-01-01",
  periodEnd: "2024-12-31",
  sites: ["All sites"],
  scopes: ["Scope 1", "Scope 2", "Scope 3"],
  format: "PDF",
  schedule: "Once",
  recipients: "",
  notes: "",
  includeCharts: true,
  includeRawData: false,
  signOff: false,
};

export default function ReportsPage() {
  const reduced = useReducedMotion();
  const [savedReports, setSavedReports] = useState<SavedReport[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewReport, setPreviewReport] = useState<SavedReport | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [filterFramework, setFilterFramework] = useState<string>("All");
  const [form, setForm] = useState<NewReportForm>(initialForm);
  const [toast, setToast] = useState<string | null>(null);

  // Load saved reports from localStorage
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as SavedReport[];
        setSavedReports(parsed);
      }
    } catch {
      /* ignore */
    }
  }, []);

  // Persist saved reports
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(savedReports));
    } catch {
      /* ignore */
    }
  }, [savedReports]);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  // All reports = seed + saved
  const allReports = useMemo(() => {
    const seed: SavedReport[] = RECENT_REPORTS.map((r) => ({
      id: String(r.id),
      name: r.name,
      framework: r.framework,
      period: r.period,
      generated: r.generated,
      size: r.size,
      status: "Completed",
      format: "PDF",
      createdAt: Date.now() - 1000 * 60 * 60 * 24 * 30,
    }));
    return [...savedReports, ...seed].sort((a, b) => b.createdAt - a.createdAt);
  }, [savedReports]);

  const filteredReports = useMemo(() => {
    return allReports.filter((r) => {
      const matchSearch = search
        ? r.name.toLowerCase().includes(search.toLowerCase()) ||
          r.framework.toLowerCase().includes(search.toLowerCase())
        : true;
      const matchFramework = filterFramework === "All" || r.framework === filterFramework;
      return matchSearch && matchFramework;
    });
  }, [allReports, search, filterFramework]);

  const frameworks = useMemo(() => {
    const set = new Set(allReports.map((r) => r.framework));
    return ["All", ...Array.from(set)];
  }, [allReports]);

  const openModalWithTemplate = (framework: string) => {
    const template = REPORT_TYPES.find((t) => t.name === framework);
    setForm({
      ...initialForm,
      framework,
      name: template ? `${template.name} — ${new Date().getFullYear()}` : "",
    });
    setModalOpen(true);
    setDropdownOpen(false);
  };

  const openModalCustom = () => {
    setForm({ ...initialForm, framework: "Custom", name: "Custom Report" });
    setModalOpen(true);
    setDropdownOpen(false);
  };

  const closeModal = () => {
    setModalOpen(false);
    setForm(initialForm);
  };

  const generateReport = () => {
    if (!form.name.trim()) {
      setToast("Please enter a report name");
      return;
    }
    const newReport: SavedReport = {
      id: `rep-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      name: form.name.trim(),
      framework: form.framework,
      period: `${form.periodStart} – ${form.periodEnd}`,
      generated: new Date().toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" }),
      size: `${(Math.random() * 5 + 1).toFixed(1)} MB`,
      status: "Completed",
      format: form.format,
      schedule: form.schedule === "Once" ? undefined : form.schedule,
      notes: form.notes,
      createdAt: Date.now(),
    };
    setSavedReports([newReport, ...savedReports]);
    closeModal();
    setToast(`Report "${newReport.name}" generated successfully`);
  };

  const deleteReport = (id: string) => {
    setSavedReports(savedReports.filter((r) => r.id !== id));
    setToast("Report deleted");
  };

  const duplicateReport = (report: SavedReport) => {
    const dup: SavedReport = {
      ...report,
      id: `rep-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      name: `${report.name} (Copy)`,
      createdAt: Date.now(),
    };
    setSavedReports([dup, ...savedReports]);
    setToast("Report duplicated");
  };

  const openPreview = (report: SavedReport) => {
    setPreviewReport(report);
    setPreviewOpen(true);
  };

  const formatIcon = (f: ReportFormat) => {
    if (f === "PDF") return <FilePdf className="h-3.5 w-3.5" />;
    if (f === "Excel") return <FileSpreadsheet className="h-3.5 w-3.5" />;
    return <FileDown className="h-3.5 w-3.5" />;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <m.div
        initial={reduced ? false : { opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"
      >
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Reports <span className="ml-1">📄</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Generate, manage, and export sustainability reports with confidence.<br />Compliant. Transparent. Audit-ready.
          </p>
        </div>

        {/* New Report dropdown */}
        <div className="relative">
          <m.button
            data-testid="new-report-button"
            onClick={() => setDropdownOpen((v) => !v)}
            className="inline-flex items-center gap-2 rounded-md bg-lime-100 px-3 py-1.5 text-xs font-semibold text-black transition-colors hover:bg-lime-200"
            whileHover={reduced ? undefined : { scale: 1.02 }}
            whileTap={reduced ? undefined : { scale: 0.98 }}
          >
            <Plus className="h-3.5 w-3.5" /> New Report <ChevronDown className="h-3 w-3" />
          </m.button>
          <AnimatePresence>
            {dropdownOpen && (
              <>
                <div
                  className="fixed inset-0 z-30"
                  onClick={() => setDropdownOpen(false)}
                />
                <m.div
                  initial={reduced ? false : { opacity: 0, y: -4, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={reduced ? undefined : { opacity: 0, y: -4, scale: 0.97 }}
                  transition={{ duration: 0.15, ease: "easeOut" }}
                  className="absolute right-0 z-40 mt-2 w-72 overflow-hidden rounded-lg border border-white/10 bg-[#0a1410]/95 shadow-2xl backdrop-blur"
                  data-testid="new-report-dropdown"
                >
                  <div className="border-b border-white/5 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                    Start from template
                  </div>
                  {REPORT_TYPES.slice(0, 6).map((t) => (
                    <button
                      key={t.id}
                      data-testid={`new-report-template-${t.id}`}
                      onClick={() => openModalWithTemplate(t.name)}
                      className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm text-white/80 transition-colors hover:bg-white/5 hover:text-white"
                    >
                      <span className="text-base">{TYPE_ICON[t.id]}</span>
                      <div className="flex-1">
                        <p className="text-sm font-medium">{t.name}</p>
                        <p className="text-[10px] text-white/40">{t.sub}</p>
                      </div>
                    </button>
                  ))}
                  <div className="border-t border-white/5" />
                  <button
                    data-testid="new-report-custom"
                    onClick={openModalCustom}
                    className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm font-medium text-emerald-100 transition-colors hover:bg-emerald-200/10"
                  >
                    <Sparkles className="h-4 w-4" />
                    <span>Custom Report Builder</span>
                  </button>
                </m.div>
              </>
            )}
          </AnimatePresence>
        </div>
      </m.div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {REPORTS_KPIS.map((k, i) => (
          <m.div
            key={k.id}
            initial={reduced ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: reduced ? 0 : i * 0.05, ease: "easeOut" }}
          >
            <KpiCard label={k.label} value={k.value} sub={k.sub} />
          </m.div>
        ))}
      </div>

      {/* Report Types + Summary */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Report Templates"
          subtitle="Choose a framework or create a custom report tailored to your needs."
          actions={<button className="text-xs text-emerald-100 hover:text-emerald-200">View all frameworks →</button>}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {REPORT_TYPES.map((t, i) => (
              <m.button
                key={t.id}
                data-testid={`template-card-${t.id}`}
                onClick={() => openModalWithTemplate(t.name)}
                className="group rounded-xl border border-white/5 bg-white/[0.02] p-4 text-left transition-colors hover:border-emerald-200/30"
                initial={reduced ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: reduced ? 0 : 0.05 + i * 0.05 }}
                whileHover={reduced ? undefined : { scale: 1.01 }}
                whileTap={reduced ? undefined : { scale: 0.99 }}
              >
                <div className="flex items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-200/10 text-lg">{TYPE_ICON[t.id]}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-white">{t.name}</p>
                    <p className="mt-1 text-xs text-white/60">{t.sub}</p>
                    <span className="mt-2 inline-flex items-center gap-1 rounded-md border border-emerald-200/30 bg-emerald-200/5 px-3 py-1 text-[10px] font-medium text-emerald-100 group-hover:bg-emerald-200/10">
                      {t.cta} →
                    </span>
                  </div>
                </div>
              </m.button>
            ))}
          </div>
        </Card>

        <div className="space-y-5">
          <Card title="Report Summary" actions={
            <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
              <option>This Year</option>
            </select>
          }>
            <div className="flex flex-col items-center">
              <DonutChart
                data={REPORT_FRAMEWORK_BREAKDOWN.map((f) => ({ label: f.label, value: f.value, color: f.color }))}
                size={160}
                thickness={20}
                centerLabel={`${REPORT_FRAMEWORK_BREAKDOWN.reduce((s, f) => s + f.value, 0)}`}
                centerSub="Total"
                formatTooltip={(label, value, pct) => (
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-white/65">Reports</span>
                      <span className="ml-auto font-mono font-medium text-white">{value}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-white/65">Share</span>
                      <span className="ml-auto font-mono font-medium text-emerald-100">{pct.toFixed(1)}%</span>
                    </div>
                  </div>
                )}
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                {REPORT_FRAMEWORK_BREAKDOWN.map((f) => (
                  <div key={f.label} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-white/70">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: f.color }} />
                      {f.label}
                    </span>
                    <span className="text-white">{f.value} ({f.percent}%)</span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          <Card title="Export formats" subtitle="All reports can be exported in multiple formats for your convenience.">
            <div className="space-y-2.5">
              {[
                { label: "Export as PDF",  icon: <FilePdf className="h-4 w-4" />, color: "rgba(244,63,94,0.95)" },
                { label: "Export as Excel", icon: <FileSpreadsheet className="h-4 w-4" />, color: "rgba(16,185,129,0.95)" },
                { label: "Export as CSV",  icon: <FileDown className="h-4 w-4" />, color: "rgba(132,204,22,0.95)" },
              ].map((row) => (
                <button
                  key={row.label}
                  className="flex w-full items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] p-2.5 text-left transition-colors hover:bg-white/5"
                >
                  <span className="grid h-8 w-8 place-items-center rounded-md" style={{ backgroundColor: row.color + "20", color: row.color }}>{row.icon}</span>
                  <span className="flex-1 text-sm text-white">{row.label}</span>
                  <span className="text-emerald-100">→</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Recent Reports + Audit Trail */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              Reports Library
              <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-normal text-white/60">
                {allReports.length}
              </span>
            </span>
          }
          subtitle="Generate, schedule, and download all your sustainability reports."
          noPadding
        >
          {/* Toolbar */}
          <div className="flex flex-col gap-2 border-b border-white/5 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative flex-1 max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
              <input
                type="text"
                placeholder="Search reports..."
                data-testid="reports-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/5 py-1.5 pl-8 pr-3 text-xs text-white placeholder:text-white/30 focus:border-emerald-200/40 focus:outline-none"
              />
            </div>
            <div className="flex items-center gap-2">
              <Filter className="h-3.5 w-3.5 text-white/40" />
              <select
                data-testid="reports-filter"
                value={filterFramework}
                onChange={(e) => setFilterFramework(e.target.value)}
                className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70"
              >
                {frameworks.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Table header */}
          <div className="grid grid-cols-6 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
            <span className="col-span-2">Report Name</span>
            <span>Framework</span>
            <span>Period</span>
            <span>Generated</span>
            <span className="text-right">Actions</span>
          </div>
          <div className="divide-y divide-white/5">
            {filteredReports.length === 0 && (
              <div className="px-5 py-8 text-center text-xs text-white/50">
                No reports match your search.
              </div>
            )}
            {filteredReports.map((row) => (
              <div
                key={row.id}
                data-testid={`report-row-${row.id}`}
                className="grid grid-cols-6 items-center gap-3 px-5 py-3 hover:bg-white/[0.02]"
              >
                <NameCell
                  icon={formatIcon(row.format)}
                  name={row.name}
                  sub={
                    <span className="flex items-center gap-1.5 text-[10px] text-white/40">
                      {row.format} • {row.size}
                      {"schedule" in row && row.schedule && (
                        <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-emerald-200/10 px-1.5 py-0.5 text-emerald-100">
                          <Clock className="h-2.5 w-2.5" /> {row.schedule}
                        </span>
                      )}
                    </span>
                  }
                />
                <Pill color="lime">{row.framework}</Pill>
                <div>
                  <p className="text-sm text-white">{row.period}</p>
                </div>
                <div>
                  <p className="text-sm text-white">{row.generated.split(",")[0]}</p>
                  <p className="text-[10px] text-white/50">{row.generated.split(",").slice(1).join(",").trim()}</p>
                </div>
                <div className="flex items-center justify-end gap-1.5">
                  <m.button
                    data-testid={`preview-report-${row.id}`}
                    onClick={() => openPreview(row)}
                    className="rounded-md border border-white/10 bg-white/5 p-1.5 text-white/60 hover:text-white"
                    whileHover={reduced ? undefined : { scale: 1.08 }}
                    whileTap={reduced ? undefined : { scale: 0.92 }}
                    aria-label="Preview report"
                  >
                    <Eye className="h-3.5 w-3.5" />
                  </m.button>
                  <m.button
                    data-testid={`download-report-${row.id}`}
                    onClick={() => setToast(`Downloading "${row.name}"...`)}
                    className="rounded-md border border-emerald-200/30 bg-emerald-200/5 p-1.5 text-emerald-100 hover:bg-emerald-200/10"
                    whileHover={reduced ? undefined : { scale: 1.08 }}
                    whileTap={reduced ? undefined : { scale: 0.92 }}
                    aria-label="Download report"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </m.button>
                  <m.button
                    data-testid={`duplicate-report-${row.id}`}
                    onClick={() => duplicateReport(row)}
                    className="rounded-md border border-white/10 bg-white/5 p-1.5 text-white/60 hover:text-white"
                    whileHover={reduced ? undefined : { scale: 1.08 }}
                    whileTap={reduced ? undefined : { scale: 0.92 }}
                    aria-label="Duplicate report"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </m.button>
                  <m.button
                    data-testid={`delete-report-${row.id}`}
                    onClick={() => deleteReport(row.id)}
                    className="rounded-md border border-rose-400/30 bg-rose-400/5 p-1.5 text-rose-300 hover:bg-rose-400/10"
                    whileHover={reduced ? undefined : { scale: 1.08 }}
                    whileTap={reduced ? undefined : { scale: 0.92 }}
                    aria-label="Delete report"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </m.button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Audit Trail" subtitle="All report activities are tracked for transparency and compliance.">
          <div className="space-y-4">
            {RECENT_REPORTS.slice(0, 3).map((r) => (
              <div key={r.id} className="flex items-start gap-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-emerald-200/10 text-emerald-100">📄</span>
                <div>
                  <p className="text-sm font-semibold text-white">{r.name}</p>
                  <p className="text-[10px] text-white/50">{r.framework === "ESG" ? "Generated by Diptu Alam" : r.framework === "GHG Protocol" ? "Downloaded by Diptu Alam" : "Exported as PDF by Diptu Alam"}</p>
                  <p className="text-[10px] text-white/40">{r.generated}</p>
                </div>
              </div>
            ))}
          </div>
          <button className="mt-4 text-xs text-emerald-100 hover:text-emerald-200">View full audit log →</button>
        </Card>
      </div>

      {/* Reports Over Time + Popular Metrics */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Reports Over Time" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Year</option>
          </select>
        }>
          <BarChart
            data={[5, 7, 5, 7, 6, 4, 2, 3, 1, 2, 1, 3]}
            labels={["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
            height={200}
            color="rgba(132,204,22,0.95)"
            formatTooltip={(label, value) => (
              <div className="flex items-center gap-2">
                <span className="text-white/65">Reports generated</span>
                <span className="ml-auto font-mono font-medium text-white">{value}</span>
              </div>
            )}
          />
          <div className="mt-2 flex items-center gap-2 text-[10px] text-white/50">
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-lime-100" /> Reports Generated</span>
          </div>
          <button className="mt-3 text-xs text-emerald-100 hover:text-emerald-200">View analytics →</button>
        </Card>

        <Card title="Popular Metrics in Reports" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Year</option>
          </select>
        }>
          <div className="space-y-3">
            {REPORT_METRICS_POPULARITY.map((metric) => (
              <div key={metric.label} className="flex items-center gap-3">
                <span className="text-base">🌿</span>
                <p className="flex-1 text-xs text-white/70">{metric.label}</p>
                <div className="h-1.5 w-32 overflow-hidden rounded-full bg-white/5">
                  <m.div
                    className="h-full rounded-full bg-lime-100"
                    style={{ width: `${(metric.value / 28) * 100}%` }}
                    initial={reduced ? false : { width: 0 }}
                    animate={{ width: `${(metric.value / 28) * 100}%` }}
                    transition={{ duration: 0.8, delay: 0.2, ease: "easeOut" }}
                  />
                </div>
                <span className="w-8 text-right text-sm font-medium text-white">{metric.value}</span>
              </div>
            ))}
          </div>
          <button className="mt-3 text-xs text-emerald-100 hover:text-emerald-200">View all metrics →</button>
        </Card>
      </div>

      {/* Need a custom report? */}
      <m.div
        className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.02] p-4"
        initial={reduced ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.2 }}
      >
        <span className="grid h-12 w-12 place-items-center rounded-full bg-emerald-200/15 text-2xl">🌿</span>
        <div className="flex-1">
          <p className="text-sm font-semibold text-white">Need a custom report?</p>
          <p className="text-xs text-white/60">Our experts can help you build a report tailored to your business and compliance needs.</p>
        </div>
        <button className="inline-flex items-center gap-1.5 rounded-md bg-lime-100 px-3 py-2 text-xs font-semibold text-black hover:bg-lime-200">
          Request Custom Report →
        </button>
      </m.div>

      {/* New Report Modal */}
      <NewReportModal
        open={modalOpen}
        form={form}
        setForm={setForm}
        onClose={closeModal}
        onSubmit={generateReport}
      />

      {/* Preview Modal */}
      <PreviewModal
        report={previewReport}
        open={previewOpen}
        onClose={() => {
          setPreviewOpen(false);
          setPreviewReport(null);
        }}
        onDownload={() => {
          if (previewReport) setToast(`Downloading "${previewReport.name}"...`);
        }}
      />

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <m.div
            initial={reduced ? false : { opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 20, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 380, damping: 28 }}
            className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-emerald-200/30 bg-[#0a1410]/95 px-4 py-2.5 text-sm font-medium text-white shadow-2xl backdrop-blur"
            data-testid="toast"
          >
            <Check className="mr-2 inline h-4 w-4 text-emerald-100" />
            {toast}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// New Report Modal
// ────────────────────────────────────────────────────────────────────

function NewReportModal({
  open,
  form,
  setForm,
  onClose,
  onSubmit,
}: {
  open: boolean;
  form: NewReportForm;
  setForm: (f: NewReportForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const reduced = useReducedMotion();
  const update = (patch: Partial<NewReportForm>) => setForm({ ...form, ...patch });
  const toggleScope = (s: "Scope 1" | "Scope 2" | "Scope 3") => {
    const next = form.scopes.includes(s)
      ? form.scopes.filter((x) => x !== s)
      : [...form.scopes, s];
    update({ scopes: next });
  };
  const toggleSite = (s: string) => {
    const next = form.sites.includes(s)
      ? form.sites.filter((x) => x !== s)
      : [...form.sites, s];
    update({ sites: next });
  };

  return (
    <AnimatePresence>
      {open && (
        <m.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          data-testid="new-report-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Create new report"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduced ? { opacity: 1 } : { opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <m.div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <m.div
            className="relative max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-xl border border-white/10 bg-[#0a1410]/95 shadow-2xl"
            initial={reduced ? false : { opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={reduced ? { opacity: 1 } : { opacity: 0, scale: 0.96, y: 6 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            data-testid="new-report-modal-content"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-4 border-b border-white/5 px-6 py-4">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
                  <FileText className="h-5 w-5 text-emerald-100" />
                  Create New Report
                </h2>
                <p className="mt-0.5 text-sm text-white/60">Configure your report, then generate or schedule it.</p>
              </div>
              <button
                onClick={onClose}
                className="grid h-8 w-8 place-items-center rounded-md border border-white/10 bg-white/5 text-white/70 hover:text-white"
                aria-label="Close"
                data-testid="new-report-close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Body */}
            <div className="max-h-[calc(90vh-180px)] overflow-y-auto px-6 py-5 text-sm text-white/80">
              {/* Name + Framework */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                    Report Name *
                  </label>
                  <input
                    type="text"
                    data-testid="report-name-input"
                    value={form.name}
                    onChange={(e) => update({ name: e.target.value })}
                    placeholder="e.g. Q4 2024 GHG Report"
                    className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-200/40 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                    Framework
                  </label>
                  <select
                    data-testid="report-framework-select"
                    value={form.framework}
                    onChange={(e) => update({ framework: e.target.value })}
                    className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
                  >
                    {REPORT_TYPES.map((t) => (
                      <option key={t.id} value={t.name}>{t.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Period */}
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                    Period Start
                  </label>
                  <input
                    type="date"
                    data-testid="report-period-start"
                    value={form.periodStart}
                    onChange={(e) => update({ periodStart: e.target.value })}
                    className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                    Period End
                  </label>
                  <input
                    type="date"
                    data-testid="report-period-end"
                    value={form.periodEnd}
                    onChange={(e) => update({ periodEnd: e.target.value })}
                    className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
                  />
                </div>
              </div>

              {/* Sites */}
              <div className="mt-4">
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                  Include Sites
                </label>
                <div className="flex flex-wrap gap-2">
                  {SITES.map((s) => {
                    const checked = form.sites.includes(s);
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => toggleSite(s)}
                        data-testid={`site-toggle-${s.toLowerCase().replace(/\s+/g, "-")}`}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
                          checked
                            ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
                            : "border-white/10 bg-white/5 text-white/60 hover:text-white"
                        }`}
                      >
                        {checked && <Check className="h-3 w-3" />}
                        {s}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Scopes */}
              <div className="mt-4">
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                  Include Emissions Scopes
                </label>
                <div className="flex flex-wrap gap-2">
                  {(["Scope 1", "Scope 2", "Scope 3"] as const).map((s) => {
                    const checked = form.scopes.includes(s);
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => toggleScope(s)}
                        data-testid={`scope-toggle-${s.toLowerCase().replace(" ", "-")}`}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
                          checked
                            ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
                            : "border-white/10 bg-white/5 text-white/60 hover:text-white"
                        }`}
                      >
                        {checked && <Check className="h-3 w-3" />}
                        {s}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Format + Schedule */}
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                    Output Format
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {(["PDF", "Excel", "CSV"] as const).map((f) => {
                      const checked = form.format === f;
                      return (
                        <button
                          key={f}
                          type="button"
                          onClick={() => update({ format: f })}
                          data-testid={`format-toggle-${f.toLowerCase()}`}
                          className={`rounded-md border px-3 py-2 text-xs font-medium transition-colors ${
                            checked
                              ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
                              : "border-white/10 bg-white/5 text-white/60 hover:text-white"
                          }`}
                        >
                          {f}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                    Schedule
                  </label>
                  <select
                    data-testid="report-schedule"
                    value={form.schedule}
                    onChange={(e) => update({ schedule: e.target.value as ScheduleFrequency })}
                    className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-emerald-200/40 focus:outline-none"
                  >
                    <option>Once</option>
                    <option>Daily</option>
                    <option>Weekly</option>
                    <option>Monthly</option>
                    <option>Quarterly</option>
                    <option>Yearly</option>
                  </select>
                </div>
              </div>

              {/* Recipients */}
              <div className="mt-4">
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                  <span className="inline-flex items-center gap-1.5">
                    <Mail className="h-3 w-3" /> Email Recipients (comma-separated)
                  </span>
                </label>
                <input
                  type="text"
                  data-testid="report-recipients"
                  value={form.recipients}
                  onChange={(e) => update({ recipients: e.target.value })}
                  placeholder="alice@example.com, bob@example.com"
                  className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-200/40 focus:outline-none"
                />
              </div>

              {/* Notes */}
              <div className="mt-4">
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-white/60">
                  Notes (optional)
                </label>
                <textarea
                  data-testid="report-notes"
                  value={form.notes}
                  onChange={(e) => update({ notes: e.target.value })}
                  rows={2}
                  placeholder="Add context for reviewers..."
                  className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-200/40 focus:outline-none"
                />
              </div>

              {/* Toggles */}
              <div className="mt-4 space-y-2 rounded-md border border-white/5 bg-white/[0.02] p-3">
                <Toggle
                  icon={<Sparkles className="h-3.5 w-3.5" />}
                  label="Include charts & visualizations"
                  checked={form.includeCharts}
                  onChange={(v) => update({ includeCharts: v })}
                  testId="toggle-charts"
                />
                <Toggle
                  icon={<FileSpreadsheet className="h-3.5 w-3.5" />}
                  label="Include raw data appendix"
                  checked={form.includeRawData}
                  onChange={(v) => update({ includeRawData: v })}
                  testId="toggle-raw"
                />
                <Toggle
                  icon={<Check className="h-3.5 w-3.5" />}
                  label="Require digital sign-off before delivery"
                  checked={form.signOff}
                  onChange={(v) => update({ signOff: v })}
                  testId="toggle-signoff"
                />
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between gap-2 border-t border-white/5 bg-white/[0.02] px-6 py-3">
              <p className="text-[10px] text-white/40">
                <Lock className="mr-1 inline h-3 w-3" /> Your report data is encrypted at rest.
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={onClose}
                  className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white"
                  data-testid="new-report-cancel"
                >
                  Cancel
                </button>
                <m.button
                  onClick={onSubmit}
                  data-testid="new-report-submit"
                  className="rounded-md bg-lime-100 px-4 py-1.5 text-xs font-semibold text-black hover:bg-lime-200"
                  whileHover={reduced ? undefined : { scale: 1.03 }}
                  whileTap={reduced ? undefined : { scale: 0.97 }}
                >
                  Generate Report
                </m.button>
              </div>
            </div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>
  );
}

function Toggle({
  icon, label, checked, onChange, testId,
}: {
  icon: React.ReactNode;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      data-testid={testId}
      className="flex w-full items-center justify-between gap-3 text-left"
    >
      <span className="flex items-center gap-2 text-sm text-white/80">
        {icon}
        {label}
      </span>
      <span
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
          checked ? "bg-emerald-200/40" : "bg-white/10"
        }`}
      >
        <m.span
          className={`inline-block h-4 w-4 transform rounded-full transition-colors ${
            checked ? "bg-lime-100" : "bg-white/40"
          }`}
          animate={{ x: checked ? 16 : 2 }}
          transition={{ type: "spring", stiffness: 500, damping: 30 }}
        />
      </span>
    </button>
  );
}

// ────────────────────────────────────────────────────────────────────
// Preview Modal
// ────────────────────────────────────────────────────────────────────

function PreviewModal({
  report,
  open,
  onClose,
  onDownload,
}: {
  report: SavedReport | null;
  open: boolean;
  onClose: () => void;
  onDownload: () => void;
}) {
  const reduced = useReducedMotion();
  return (
    <AnimatePresence>
      {open && report && (
        <m.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          data-testid="preview-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Report preview"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduced ? { opacity: 1 } : { opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <m.div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <m.div
            className="relative max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-xl border border-white/10 bg-[#0a1410]/95 shadow-2xl"
            initial={reduced ? false : { opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={reduced ? { opacity: 1 } : { opacity: 0, scale: 0.96, y: 6 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-white/5 px-6 py-4">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
                  <Eye className="h-5 w-5 text-emerald-100" />
                  Report Preview
                </h2>
                <p className="mt-0.5 text-sm text-white/60">{report.name}</p>
              </div>
              <button
                onClick={onClose}
                className="grid h-8 w-8 place-items-center rounded-md border border-white/10 bg-white/5 text-white/70 hover:text-white"
                aria-label="Close preview"
                data-testid="preview-close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[calc(90vh-180px)] overflow-y-auto px-6 py-5 text-sm text-white/80">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Framework", value: report.framework, tone: "default" as const },
                  { label: "Period", value: report.period, tone: "default" as const },
                  { label: "Generated", value: report.generated, tone: "default" as const },
                  { label: "Size", value: report.size, tone: "default" as const },
                  { label: "Format", value: report.format, tone: "default" as const },
                  { label: "Status", value: report.status, tone: "positive" as const },
                  ...(report.schedule ? [{ label: "Recurring", value: report.schedule, tone: "default" as const }] : []),
                ].map((f, i) => (
                  <m.div
                    key={f.label}
                    className="rounded-md border border-white/5 bg-white/5 p-3"
                    initial={reduced ? false : { opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2, delay: reduced ? 0 : 0.04 + i * 0.025 }}
                  >
                    <p className="text-[10px] uppercase tracking-wide text-white/50">{f.label}</p>
                    <p className={`mt-0.5 font-mono text-sm font-medium ${f.tone === "positive" ? "text-emerald-100" : "text-white"}`}>
                      {f.value}
                    </p>
                  </m.div>
                ))}
              </div>

              <div className="mt-5 rounded-md border border-white/5 bg-white/[0.02] p-4">
                <p className="text-[10px] uppercase tracking-wide text-white/50">Contents</p>
                <ul className="mt-2 space-y-1.5 text-sm text-white/80">
                  <li>• Cover page with company branding</li>
                  <li>• Executive summary</li>
                  <li>• Methodology (aligned with framework: {report.framework})</li>
                  <li>• Emissions breakdown by source and scope</li>
                  <li>• Year-over-year comparison</li>
                  <li>• Reduction opportunities and progress against targets</li>
                  <li>• Appendices with raw data tables</li>
                </ul>
              </div>

              {report.notes && (
                <div className="mt-4 rounded-md border border-white/5 bg-white/[0.02] p-4">
                  <p className="text-[10px] uppercase tracking-wide text-white/50">Notes</p>
                  <p className="mt-1.5 text-sm text-white/80">{report.notes}</p>
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-white/5 bg-white/[0.02] px-6 py-3">
              <button
                onClick={onClose}
                className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white"
                data-testid="preview-close-btn"
              >
                Close
              </button>
              <m.button
                onClick={() => {
                  onDownload();
                  onClose();
                }}
                data-testid="preview-download"
                className="inline-flex items-center gap-1.5 rounded-md bg-lime-100 px-3 py-1.5 text-xs font-semibold text-black hover:bg-lime-200"
                whileHover={reduced ? undefined : { scale: 1.03 }}
                whileTap={reduced ? undefined : { scale: 0.97 }}
              >
                <Download className="h-3.5 w-3.5" />
                Download {report.format}
              </m.button>
            </div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>
  );
}
