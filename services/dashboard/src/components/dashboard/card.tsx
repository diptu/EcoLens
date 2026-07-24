/**
 * Card — the most common container in the dashboard.
 * Header (title + optional badge/buttons) + body.
 */
import { cn } from "@/lib/utils";

export function Card({
  title,
  subtitle,
  badge,
  actions,
  className,
  children,
  noPadding,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
  noPadding?: boolean;
}) {
  return (
    <section className={cn("rounded-xl border border-white/5 bg-white/[0.02]", className)}>
      {(title || actions || badge) && (
        <header className="flex items-start justify-between gap-3 border-b border-white/5 px-5 py-4">
          <div className="min-w-0">
            {title && (
              <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                {title}
                {badge}
              </h3>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-white/50">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(noPadding ? "" : "p-5")}>{children}</div>
    </section>
  );
}
