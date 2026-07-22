/**
 * Shared two-panel auth layout.
 *  - Left: dark forest/landscape backdrop, EcoLens logo, tagline, decorative illustration
 *  - Right: form card on dark canvas
 *
 * Used by /login, /signup, /forgot-password, /reset-password,
 * /verify-email, /onboarding.
 */
import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";

export interface AuthPanelProps {
  /** "eco" = earth, "sapling" = plant, "plane" = paper plane, "shield" = lock shield */
  illustration: "eco" | "sapling" | "plane" | "shield" | "list" | "steps";
  tagline: React.ReactNode;
  /** Optional slot above tagline (e.g. feature list, step indicator) */
  topSlot?: React.ReactNode;
  /** Optional sub-tagline below main tagline */
  subTagline?: React.ReactNode;
  /** Form panel (right side) */
  children: React.ReactNode;
  /** Background image override (default: forest.webp) */
  backgroundImage?: string;
  /** Whether to show the EcoLens logo at top of left panel */
  showLogo?: boolean;
}

function AuthIllustration({ kind }: { kind: AuthPanelProps["illustration"] }) {
  // 240x240 illustrations rendered inline as SVG so they never 404
  // and stay sharp at any size.
  switch (kind) {
    case "eco":
      return (
        <svg viewBox="0 0 240 240" className="h-44 w-44 md:h-56 md:w-56" aria-hidden="true">
          <defs>
            <radialGradient id="eco-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="rgba(132,204,22,0.45)" />
              <stop offset="60%" stopColor="rgba(132,204,22,0.1)" />
              <stop offset="100%" stopColor="rgba(132,204,22,0)" />
            </radialGradient>
            <linearGradient id="eco-sphere" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="rgba(132,204,22,0.18)" />
              <stop offset="100%" stopColor="rgba(16,185,129,0.05)" />
            </linearGradient>
          </defs>
          <circle cx="120" cy="120" r="110" fill="url(#eco-glow)" />
          <circle cx="120" cy="120" r="62" fill="url(#eco-sphere)" stroke="rgba(132,204,22,0.55)" strokeWidth="0.8" />
          {/* wireframe meridians */}
          <ellipse cx="120" cy="120" rx="62" ry="20" fill="none" stroke="rgba(132,204,22,0.45)" strokeWidth="0.6" />
          <ellipse cx="120" cy="120" rx="62" ry="40" fill="none" stroke="rgba(132,204,22,0.35)" strokeWidth="0.5" />
          <ellipse cx="120" cy="120" rx="20" ry="62" fill="none" stroke="rgba(132,204,22,0.45)" strokeWidth="0.6" />
          <ellipse cx="120" cy="120" rx="40" ry="62" fill="none" stroke="rgba(132,204,22,0.35)" strokeWidth="0.5" />
          {/* nodes */}
          {Array.from({ length: 14 }).map((_, i) => {
            const a = (i / 14) * Math.PI * 2;
            return <circle key={i} cx={120 + Math.cos(a) * 62} cy={120 + Math.sin(a) * 20} r="1.5" fill="rgba(190,242,100,0.95)" />;
          })}
          {Array.from({ length: 10 }).map((_, i) => {
            const a = (i / 10) * Math.PI * 2;
            return <circle key={`v${i}`} cx={120 + Math.cos(a) * 20} cy={120 + Math.sin(a) * 62} r="1.5" fill="rgba(190,242,100,0.85)" />;
          })}
        </svg>
      );
    case "sapling":
      return (
        <svg viewBox="0 0 240 240" className="h-44 w-44 md:h-56 md:w-56" aria-hidden="true">
          <defs>
            <radialGradient id="sap-glow" cx="50%" cy="60%" r="55%">
              <stop offset="0%" stopColor="rgba(132,204,22,0.45)" />
              <stop offset="100%" stopColor="rgba(132,204,22,0)" />
            </radialGradient>
          </defs>
          <circle cx="120" cy="150" r="90" fill="url(#sap-glow)" />
          {/* stem */}
          <path d="M120 195 V130" stroke="rgba(132,204,22,0.9)" strokeWidth="2.5" strokeLinecap="round" />
          {/* left leaf */}
          <path d="M120 145 C 95 135 80 110 75 90 C 100 95 115 120 120 145 Z" fill="rgba(132,204,22,0.7)" />
          <path d="M120 145 L 78 92" stroke="rgba(190,242,100,0.9)" strokeWidth="1" />
          {/* right leaf */}
          <path d="M120 130 C 145 122 162 95 168 75 C 142 80 125 105 120 130 Z" fill="rgba(132,204,22,0.85)" />
          <path d="M120 130 L 165 78" stroke="rgba(190,242,100,0.9)" strokeWidth="1" />
          {/* center leaf */}
          <path d="M120 110 C 110 95 110 75 120 60 C 130 75 130 95 120 110 Z" fill="rgba(190,242,100,0.95)" />
        </svg>
      );
    case "plane":
      return (
        <svg viewBox="0 0 240 240" className="h-44 w-44 md:h-56 md:w-56" aria-hidden="true">
          <defs>
            <linearGradient id="plane-grad" x1="0" x2="1" y1="0" y2="1">
              <stop offset="0%" stopColor="rgba(255,255,255,0.95)" />
              <stop offset="100%" stopColor="rgba(190,242,100,0.9)" />
            </linearGradient>
          </defs>
          {/* dotted trail */}
          <path d="M40 200 Q 80 180 110 150 T 175 75" fill="none" stroke="rgba(132,204,22,0.4)" strokeWidth="1.5" strokeDasharray="3 5" />
          {/* plane */}
          <g transform="translate(155 60) rotate(-30)">
            <path d="M0 0 L60 8 L62 12 L8 18 L0 30 L-6 14 L-30 12 L-32 8 L-6 6 Z" fill="url(#plane-grad)" />
            <path d="M8 18 L62 12" stroke="rgba(132,204,22,0.6)" strokeWidth="0.8" />
          </g>
        </svg>
      );
    case "shield":
      return (
        <svg viewBox="0 0 240 240" className="h-44 w-44 md:h-56 md:w-56" aria-hidden="true">
          <defs>
            <linearGradient id="shield-grad" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="rgba(132,204,22,0.95)" />
              <stop offset="100%" stopColor="rgba(16,185,129,0.55)" />
            </linearGradient>
          </defs>
          <path
            d="M120 30 L195 55 V130 C 195 175 160 200 120 215 C 80 200 45 175 45 130 V55 Z"
            fill="rgba(132,204,22,0.18)"
            stroke="url(#shield-grad)"
            strokeWidth="2"
          />
          {/* lock body */}
          <rect x="95" y="115" width="50" height="40" rx="6" fill="rgba(132,204,22,0.85)" />
          <path d="M103 115 V100 C 103 88 113 80 120 80 C 127 80 137 88 137 100 V115" fill="none" stroke="rgba(190,242,100,0.95)" strokeWidth="3" />
          <circle cx="120" cy="135" r="4" fill="rgba(15,30,15,0.95)" />
          <rect x="118" y="135" width="4" height="10" fill="rgba(15,30,15,0.95)" />
        </svg>
      );
    default:
      return null;
  }
}

export function AuthLayout({
  illustration,
  tagline,
  topSlot,
  subTagline,
  children,
  backgroundImage = "/images/forest.webp",
  showLogo = true,
}: AuthPanelProps) {
  return (
    <div className="min-h-screen w-full bg-[#0a1410] text-white">
      <div className="grid min-h-screen w-full grid-cols-1 lg:grid-cols-2">
        {/* ───────────── Left: visual panel ───────────── */}
        <div className="relative isolate hidden min-h-screen overflow-hidden lg:block">
          {/* Background image */}
          <Image
            src={backgroundImage}
            alt=""
            fill
            priority
            sizes="50vw"
            className="object-cover opacity-60"
          />
          {/* Dark gradient overlays for legibility */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "linear-gradient(180deg, rgba(8,18,12,0.55) 0%, rgba(8,18,12,0.25) 30%, rgba(8,18,12,0.7) 80%, rgba(8,18,12,0.95) 100%)",
            }}
          />
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(circle at 30% 50%, rgba(132,204,22,0.18) 0%, transparent 60%)",
            }}
          />

          <div className="relative flex h-full flex-col px-10 py-10">
            {/* Logo */}
            {showLogo && (
              <Link href="/" className="inline-flex items-center gap-2 text-lg font-bold text-white">
                <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
                  <path d="M16 2 C 22 8 26 14 26 20 C 26 26 22 30 16 30 C 10 30 6 26 6 20 C 6 14 10 8 16 2 Z" fill="rgba(132,204,22,0.9)" />
                  <path d="M16 8 V28" stroke="rgba(8,18,12,1)" strokeWidth="1.2" />
                  <path d="M16 14 C 12 14 9 12 9 12" stroke="rgba(8,18,12,1)" strokeWidth="1" fill="none" />
                  <path d="M16 20 C 20 20 23 18 23 18" stroke="rgba(8,18,12,1)" strokeWidth="1" fill="none" />
                </svg>
                EcoLens
              </Link>
            )}

            {/* Tagline + illustration */}
            <div className="mt-auto flex flex-1 flex-col items-center justify-center text-center">
              {topSlot && <div className="mb-6 w-full max-w-sm">{topSlot}</div>}
              <h2 className="max-w-md text-3xl font-bold leading-tight md:text-4xl">
                {tagline}
              </h2>
              {subTagline && (
                <p className="mt-3 max-w-sm text-sm text-white/65">{subTagline}</p>
              )}
              <div className="mt-10">
                <AuthIllustration kind={illustration} />
              </div>
            </div>

            {/* Bottom tagline */}
            <p className="text-xs text-white/40">© {new Date().getFullYear()} EcoLens Technologies Ltd. · Sustainability starts here.</p>
          </div>
        </div>

        {/* ───────────── Right: form panel ───────────── */}
        <div className="relative flex min-h-screen flex-col items-center justify-center px-5 py-10 sm:px-8">
          {/* Mobile-only logo */}
          <div className="absolute left-5 top-5 lg:hidden">
            <Link href="/" className="inline-flex items-center gap-2 text-base font-bold text-white">
              <svg viewBox="0 0 32 32" className="h-6 w-6" aria-hidden="true">
                <path d="M16 2 C 22 8 26 14 26 20 C 26 26 22 30 16 30 C 10 30 6 26 6 20 C 6 14 10 8 16 2 Z" fill="rgba(132,204,22,0.9)" />
                <path d="M16 8 V28" stroke="rgba(8,18,12,1)" strokeWidth="1.2" />
              </svg>
              EcoLens
            </Link>
          </div>
          <div className="w-full max-w-md">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Form field row — used in every auth page */
export function AuthField({
  label,
  type = "text",
  placeholder,
  rightHint,
  name,
  defaultValue,
  autoComplete,
  icon,
}: {
  label: string;
  type?: string;
  placeholder?: string;
  rightHint?: React.ReactNode;
  name?: string;
  defaultValue?: string;
  autoComplete?: string;
  icon?: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-white/70">{label}</span>
      <span className="relative block">
        {icon && (
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-white/40">
            {icon}
          </span>
        )}
        <input
          type={type}
          name={name}
          defaultValue={defaultValue}
          placeholder={placeholder}
          autoComplete={autoComplete}
          className={cn(
            "w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-sm text-white placeholder:text-white/35",
            "focus:border-emerald-400/60 focus:outline-none focus:ring-1 focus:ring-emerald-400/30",
            icon && "pl-9",
          )}
        />
      </span>
      {rightHint && <span className="mt-1 block text-[11px] text-white/50">{rightHint}</span>}
    </label>
  );
}

/** Lime primary button */
export function AuthButton({
  children,
  type = "button",
  variant = "primary",
  className,
  fullWidth = true,
  onClick,
}: {
  children: React.ReactNode;
  type?: "button" | "submit";
  variant?: "primary" | "outline";
  className?: string;
  fullWidth?: boolean;
  onClick?: () => void;
}) {
  const base =
    variant === "primary"
      ? "bg-lime-300 text-black hover:bg-lime-200"
      : "border border-white/10 bg-white/[0.04] text-white/80 hover:bg-white/[0.07] hover:text-white";
  return (
    <button
      type={type}
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-semibold transition-colors",
        fullWidth && "w-full",
        base,
        className,
      )}
    >
      {children}
    </button>
  );
}

/** "or continue with" divider */
export function AuthDivider({ label = "or continue with" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <span className="h-px flex-1 bg-white/10" />
      <span className="text-[11px] uppercase tracking-wider text-white/40">{label}</span>
      <span className="h-px flex-1 bg-white/10" />
    </div>
  );
}

/** Social auth button */
export function SocialAuthButton({ provider }: { provider: "Google" | "Microsoft" }) {
  return (
    <button
      type="button"
      className="inline-flex flex-1 items-center justify-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 py-2.5 text-xs font-medium text-white/80 hover:bg-white/[0.07] hover:text-white"
    >
      {provider === "Google" ? (
        <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
          <path fill="#EA4335" d="M12 11v3.2h6.4c-.3 1.7-2 5-6.4 5-3.9 0-7-3.2-7-7.1s3.1-7.1 7-7.1c2.2 0 3.7 1 4.6 1.8l3.1-3C17.6 2 15.1 1 12 1 5.9 1 1 5.9 1 12s4.9 11 11 11c6.4 0 10.6-4.5 10.6-10.8 0-.7-.1-1.3-.2-1.9H12z" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
          <rect width="11" height="11" x="1" y="1" fill="#F25022" />
          <rect width="11" height="11" x="12" y="1" fill="#7FBA00" />
          <rect width="11" height="11" x="1" y="12" fill="#00A4EF" />
          <rect width="11" height="11" x="12" y="12" fill="#FFB900" />
        </svg>
      )}
      {provider}
    </button>
  );
}

/** Page header for right panel — title + breadcrumb-style link */
export function AuthHeader({
  title,
  breadcrumb,
}: {
  title: string;
  breadcrumb: { label: string; href: string };
}) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <h1 className="text-2xl font-bold text-white">{title}</h1>
      <Link
        href={breadcrumb.href}
        className="text-xs text-emerald-300 hover:text-emerald-200"
      >
        {breadcrumb.label}
      </Link>
    </div>
  );
}

/** Footer text under the form */
export function AuthFooter({ text, linkLabel, linkHref }: { text: string; linkLabel: string; linkHref: string }) {
  return (
    <p className="mt-6 text-center text-xs text-white/50">
      {text}{" "}
      <Link href={linkHref} className="text-emerald-300 hover:text-emerald-200">
        {linkLabel}
      </Link>
    </p>
  );
}
