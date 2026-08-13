/**
 * DetailModal — generic animated modal for "View details" drill-downs.
 *
 * Fade + scale in, click-outside to close, Esc to close.
 * Respects `prefers-reduced-motion` via framer-motion's `useReducedMotion`.
 */
"use client";

import { useEffect } from "react";
import { AnimatePresence, m, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";

export interface DetailField {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "positive" | "warning" | "negative";
}

export function DetailModal({
  open,
  onClose,
  title,
  subtitle,
  fields,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  fields?: DetailField[];
  children?: React.ReactNode;
}) {
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <m.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          data-testid="detail-modal"
          role="dialog"
          aria-modal="true"
          aria-label={title}
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduced ? { opacity: 1 } : { opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <m.div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <m.div
            className="relative w-full max-w-2xl overflow-hidden rounded-xl border border-white/10 bg-[#0a1410]/95 shadow-2xl"
            data-testid="detail-modal-content"
            initial={reduced ? false : { opacity: 0, scale: 0.94, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={reduced ? { opacity: 1 } : { opacity: 0, scale: 0.96, y: 6 }}
            transition={{ type: "spring", stiffness: 380, damping: 32 }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-white/5 px-5 py-4">
              <div>
                <h2 className="text-lg font-semibold text-white">{title}</h2>
                {subtitle && <p className="mt-0.5 text-sm text-white/60">{subtitle}</p>}
              </div>
              <m.button
                onClick={onClose}
                className="grid h-8 w-8 place-items-center rounded-md border border-white/10 bg-white/5 text-white/70 hover:text-white"
                aria-label="Close detail modal"
                data-testid="detail-modal-close"
                whileHover={reduced ? undefined : { scale: 1.05 }}
                whileTap={reduced ? undefined : { scale: 0.95 }}
                transition={{ type: "spring", stiffness: 400, damping: 25 }}
              >
                <X className="h-4 w-4" />
              </m.button>
            </div>
            <div className="max-h-[70vh] overflow-y-auto px-5 py-4 text-sm text-white/80">
              {fields && fields.length > 0 && (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {fields.map((f, i) => (
                    <m.div
                      key={i}
                      className="rounded-md border border-white/5 bg-white/5 p-3"
                      data-testid={`detail-field-${f.label.toLowerCase().replace(/\s+/g, "-")}`}
                      initial={reduced ? false : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: 0.2,
                        delay: reduced ? 0 : 0.04 + i * 0.025,
                        ease: "easeOut",
                      }}
                    >
                      <p className="text-[10px] uppercase tracking-wide text-white/50">{f.label}</p>
                      <p
                        className={
                          "mt-0.5 font-mono text-base font-medium " +
                          (f.tone === "positive"
                            ? "text-emerald-100"
                            : f.tone === "warning"
                              ? "text-amber-200"
                              : f.tone === "negative"
                                ? "text-rose-200"
                                : "text-white")
                        }
                      >
                        {f.value}
                      </p>
                      {f.hint && <p className="mt-1 text-[10px] text-white/40">{f.hint}</p>}
                    </m.div>
                  ))}
                </div>
              )}
              {children}
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-white/5 px-5 py-3">
              <m.button
                onClick={onClose}
                className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white"
                data-testid="detail-modal-dismiss"
                whileHover={reduced ? undefined : { scale: 1.02 }}
                whileTap={reduced ? undefined : { scale: 0.97 }}
              >
                Close
              </m.button>
            </div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>
  );
}
