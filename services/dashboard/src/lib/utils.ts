/**
 * Tiny utility helpers. Mirrors shadcn's cn() so the rest of the
 * motion components compose cleanly with the UI primitives.
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Classify a number as a "badge" — used in section labels like "AI-POWERED". */
export function asBadgeText(text: string): string {
  return text.toUpperCase();
}
