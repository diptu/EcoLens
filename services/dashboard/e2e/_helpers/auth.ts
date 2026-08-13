/**
 * Auth helpers for the e2e tests.
 *
 * `loginAs(page, "diptu")` — injects a valid-shaped session directly into
 * localStorage. `clearAuth(page)` — clears the localStorage session.
 *
 * Deliberately does NOT drive the real login form / IAM backend: these
 * helpers exist for tests that need to be *signed in* to exercise some
 * other page (dashboard, reports, ...) — the sign-in mechanism itself is
 * covered by e2e/auth.spec.ts, which does mock the IAM network calls via
 * page.route() and drives the real form. Injecting the session directly
 * here keeps every other spec hermetic (no IAM/Postgres needed) and fast.
 */
import type { Page } from "@playwright/test";

type SeedUser = {
  username: string;
  email: string;
  name: string;
  initials: string;
  role: "admin" | "analyst" | "viewer";
  region: string;
};

const USERS: Record<"diptu" | "demo", SeedUser> = {
  diptu: {
    username: "diptu",
    email: "diptu@ecolens.com",
    name: "Diptu Alam",
    initials: "DA",
    role: "admin",
    region: "AU",
  },
  demo: {
    username: "demo",
    email: "demo@ecolens.app",
    name: "Demo User",
    initials: "DU",
    role: "analyst",
    region: "AU",
  },
};

/**
 * Sign in as a seeded user by writing a session straight into
 * localStorage, shaped exactly like `src/lib/auth.ts`'s `AuthSession`.
 */
export async function loginAs(page: Page, username: "diptu" | "demo"): Promise<void> {
  const user = USERS[username];
  const now = Date.now();
  const session = {
    user,
    issuedAt: now,
    expiresAt: now + 60 * 60 * 1000,
    token: `e2e-fixture.${username}.${now}`,
    refreshToken: `e2e-fixture-refresh.${username}.${now}`,
  };
  // Needs a same-origin page loaded before localStorage is writable.
  await page.goto("/login/");
  await page.evaluate((s) => {
    window.localStorage.setItem("ecolens.session", JSON.stringify(s));
  }, session);
}

/**
 * Clear any localStorage session. Safe to call even when not signed in.
 */
export async function clearAuth(page: Page): Promise<void> {
  await page.evaluate(() => window.localStorage.removeItem("ecolens.session"));
}
