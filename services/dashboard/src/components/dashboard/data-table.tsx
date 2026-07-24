/**
 * DataTable — generic table with header row, rows, optional
 * per-row icon, badges, and an actions column (the "..." menu
 * in every dashboard table).
 */
import { MoreHorizontal } from "lucide-react";

import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: React.ReactNode;
  className?: string;
  /** Render the cell value. Return a ReactNode. */
  render: (row: T, i: number) => React.ReactNode;
  align?: "left" | "right" | "center";
}

export function DataTable<T extends { id: string | number }>({
  columns,
  rows,
  className,
  emptyMessage = "No rows.",
}: {
  columns: Column<T>[];
  rows: readonly T[];
  className?: string;
  emptyMessage?: string;
}) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/5 text-left text-[11px] font-medium uppercase tracking-wider text-white/40">
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "px-4 py-3",
                  c.align === "right" && "text-right",
                  c.align === "center" && "text-center",
                  c.className,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-sm text-white/40">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={row.id}
                className="border-b border-white/5 last:border-b-0 transition-colors hover:bg-white/[0.02]"
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn(
                      "px-4 py-3 align-middle",
                      c.align === "right" && "text-right",
                      c.align === "center" && "text-center",
                      c.className,
                    )}
                  >
                    {c.render(row, i)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ─────────────────  Reusable cells  ───────────────── */

export function NameCell({
  icon,
  name,
  sub,
}: {
  icon?: React.ReactNode;
  name: string;
  sub?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      {icon && (
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md border border-white/5 bg-white/[0.04]">
          {icon}
        </span>
      )}
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-white">{name}</p>
        {sub && <p className="truncate text-xs text-white/50">{sub}</p>}
      </div>
    </div>
  );
}

export function StatusDot({ color, label }: { color: "green" | "amber" | "red" | "gray"; label?: string }) {
  const c = {
    green: "bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.6)]",
    amber: "bg-amber-400",
    red:   "bg-rose-400",
    gray:  "bg-white/30",
  }[color];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={cn("h-1.5 w-1.5 rounded-full", c)} />
      {label && <span className="text-white/70">{label}</span>}
    </span>
  );
}

export function Pill({
  children,
  color = "gray",
  className,
}: {
  children: React.ReactNode;
  color?: "gray" | "lime" | "emerald" | "purple" | "sky" | "amber" | "rose";
  className?: string;
}) {
  const styles: Record<NonNullable<typeof color>, string> = {
    gray:    "border-white/10 bg-white/5 text-white/70",
    lime:    "border-lime-400/30 bg-lime-400/10 text-lime-300",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
    purple:  "border-purple-400/30 bg-purple-400/10 text-purple-300",
    sky:     "border-sky-400/30 bg-sky-400/10 text-sky-300",
    amber:   "border-amber-400/30 bg-amber-400/10 text-amber-300",
    rose:    "border-rose-400/30 bg-rose-400/10 text-rose-300",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        styles[color],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function ActionsMenu() {
  return (
    <button
      type="button"
      className="grid h-7 w-7 place-items-center rounded-full text-white/40 transition-colors hover:bg-white/5 hover:text-white"
      aria-label="Actions"
    >
      <MoreHorizontal className="h-4 w-4" />
    </button>
  );
}
