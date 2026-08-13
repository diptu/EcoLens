/**
 * IllustrativeBadge — the one consistent marker for a section that has no
 * real backend behind it yet. This app enforces "no silently fabricated
 * dashboards" (see `models/page.tsx`'s honest empty states vs
 * `training/page.tsx`'s known precedent violation) — any card showing
 * illustrative/sample numbers must carry this, no exceptions, so a reader
 * can tell real from mock at a glance without reading the fine print.
 */
import { FlaskConical } from "lucide-react";

export function IllustrativeBadge({ label = "Illustrative — not wired to live data" }: { label?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-dashed border-amber-300/40 bg-amber-300/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-200"
      title={label}
    >
      <FlaskConical className="h-3 w-3" />
      {label}
    </span>
  );
}
