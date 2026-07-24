/**
 * Reusable motion button — wraps shadcn Button with hover/tap
 * Framer Motion micro-interactions.
 */
"use client";

import { m, type HTMLMotionProps } from "framer-motion";
import { forwardRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "outline";
type ButtonSize = "sm" | "md" | "lg";

export interface MotionButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  iconAfter?: ReactNode;
  iconBefore?: ReactNode;
  children: ReactNode;
}

const baseClasses =
  "relative inline-flex items-center justify-center gap-2 font-semibold rounded-full " +
  "transition-colors duration-200 ease-out focus:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#050a08] " +
  "disabled:opacity-50 disabled:pointer-events-none select-none";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-lime-300 text-black hover:bg-lime-200 active:bg-lime-400 " +
    "shadow-[0_0_24px_-4px_rgba(132,204,22,0.45)]",
  secondary:
    "bg-white/5 backdrop-blur-md text-white border border-white/10 " +
    "hover:bg-white/10 hover:border-white/20",
  ghost: "bg-transparent text-white hover:bg-white/5",
  outline:
    "bg-transparent text-white border border-emerald-400/40 " +
    "hover:bg-emerald-400/10 hover:border-emerald-400/60",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-9 px-4 text-sm",
  md: "h-11 px-6 text-sm",
  lg: "h-12 px-7 text-base",
};

export const MotionButton = forwardRef<HTMLButtonElement, MotionButtonProps>(
  function MotionButton(
    {
      children,
      className,
      variant = "primary",
      size = "md",
      iconAfter,
      iconBefore,
      disabled,
      ...rest
    },
    ref,
  ) {
    return (
      <m.button
        ref={ref}
        className={cn(baseClasses, variantClasses[variant], sizeClasses[size], className)}
        disabled={disabled}
        whileHover={disabled ? undefined : { scale: 1.02 }}
        whileTap={disabled ? undefined : { scale: 0.97 }}
        transition={{ type: "spring", stiffness: 400, damping: 25 }}
        {...rest}
      >
        {iconBefore && <span className="inline-flex items-center">{iconBefore}</span>}
        <span>{children}</span>
        {iconAfter && (
          <span
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-full",
              variant === "primary"
                ? "bg-black/15"
                : variant === "outline"
                  ? "bg-emerald-400/20"
                  : "bg-white/10",
            )}
          >
            {iconAfter}
          </span>
        )}
      </m.button>
    );
  },
);
