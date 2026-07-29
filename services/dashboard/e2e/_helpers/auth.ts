/**
 * Auth helpers for the e2e tests.
 *
 * `loginAs(page, "diptu")` — fills the login form and submits.
 * `clearAuth(page)`        — clears the localStorage session.
 */
import type { Page } from "@playwright/test";

/**
 * Sign in via the login form.
 *
 * If `username` is "diptu" the password is "Hello123" (the canonical
 * admin account). Otherwise we treat it as the demo user.
 */
export async function loginAs(page: Page, username: "diptu" | "demo"): Promise<void> {
  await page.goto("/login/");
  await clearAuth(page);
  await page.getByLabel(/Email or username/i).fill(username);
  await page.locator('input[name="password"]').fill(username === "diptu" ? "Hello123" : "demo1234");
  await page.getByRole("button", { name: "Sign In" }).click();
  // Wait until the localStorage session is populated
  await page.waitForFunction(() => window.localStorage.getItem("ecolens.session") !== null);
}

/**
 * Clear any localStorage session. Safe to call even when not signed in.
 */
export async function clearAuth(page: Page): Promise<void> {
  await page.evaluate(() => window.localStorage.removeItem("ecolens.session"));
}
