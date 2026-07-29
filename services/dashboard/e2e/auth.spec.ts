/**
 * E2E tests for the /login, /signup, /forgot-password, /reset-password,
 * /verify-email, and /onboarding pages.
 */
import { test, expect } from "@playwright/test";

const ROUTES = [
  "/login/",
  "/signup/",
  "/forgot-password/",
  "/reset-password/",
  "/verify-email/",
  "/onboarding/",
] as const;

for (const route of ROUTES) {
  test(`renders ${route} with two-panel layout + EcoLens brand`, async ({ page }) => {
    await page.goto(route);
    // EcoLens logo is in the layout
    const logos = page.getByText("EcoLens");
    expect(await logos.count()).toBeGreaterThan(0);
    // Has an h1 (form title)
    await expect(page.locator("h1").first()).toBeVisible();
    // No navbar/footer (this is /auth not /inner)
    await expect(page.locator("nav").first()).toHaveCount(0);
  });
}

test.describe("/login", () => {
  test("renders form with email + password + Sign In", async ({ page }) => {
    await page.goto("/login/");
    await expect(page.getByRole("heading", { name: "Login" })).toBeVisible();
    await expect(page.getByLabel(/Email or username/i)).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Google/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Microsoft/ })).toBeVisible();
    await expect(page.getByText("Forgot password?")).toBeVisible();
    await expect(page.getByText("Don't have an account?")).toBeVisible();
    // Pre-filled demo credentials are shown so the tester doesn't have to dig.
    await expect(page.getByText(/Demo credentials/i)).toBeVisible();
    await expect(page.getByText("diptu")).toBeVisible();
    await expect(page.getByText("Hello123")).toBeVisible();
  });

  test("'Sign up' link goes to /signup", async ({ page }) => {
    await page.goto("/login/");
    await page.getByRole("link", { name: "Sign up" }).click();
    await page.waitForURL(/\/signup/);
  });

  test("'Forgot password?' link goes to /forgot-password", async ({ page }) => {
    await page.goto("/login/");
    await page.getByRole("link", { name: "Forgot password?" }).click();
    await page.waitForURL(/\/forgot-password/);
  });

  test("signs in successfully with diptu / Hello123 and redirects to /dashboard/executive", async ({ page }) => {
    await page.goto("/login/");
    // The form pre-fills the credentials (it's the demo account).
    await page.getByLabel(/Email or username/i).fill("diptu");
    await page.locator('input[name="password"]').fill("Hello123");
    await page.getByTestId("login-submit").click();
    await page.waitForURL(/\/dashboard\/executive\/?$/, { timeout: 10_000 });
    // Session is in localStorage
    const session = await page.evaluate(() => window.localStorage.getItem("ecolens.session"));
    expect(session).toBeTruthy();
    const parsed = JSON.parse(session!);
    expect(parsed.user.username).toBe("diptu");
    expect(parsed.user.role).toBe("admin");
  });

  test("shows an error for a wrong password and does not navigate", async ({ page }) => {
    await page.goto("/login/");
    await page.getByLabel(/Email or username/i).fill("diptu");
    await page.locator('input[name="password"]').fill("NotTheRightPassword");
    await page.getByTestId("login-submit").click();
    const err = page.getByTestId("login-error");
    await expect(err).toBeVisible({ timeout: 5_000 });
    await expect(err).toContainText(/password doesn't match/i);
    // Still on /login
    expect(page.url()).toMatch(/\/login/);
  });

  test("shows an error for an unknown user", async ({ page }) => {
    await page.goto("/login/");
    await page.getByLabel(/Email or username/i).fill("nobody@example.com");
    await page.locator('input[name="password"]').fill("whatever");
    await page.getByTestId("login-submit").click();
    const err = page.getByTestId("login-error");
    await expect(err).toBeVisible({ timeout: 5_000 });
    await expect(err).toContainText(/couldn't find an account/i);
  });

  test("show/hide password toggle changes input type", async ({ page }) => {
    await page.goto("/login/");
    const pw = page.locator('input[name="password"]');
    await expect(pw).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: /Show password/ }).click();
    await expect(pw).toHaveAttribute("type", "text");
    await page.getByRole("button", { name: /Hide password/ }).click();
    await expect(pw).toHaveAttribute("type", "password");
  });

  test("topbar profile chip shows the signed-in user's name after login", async ({ page }) => {
    await page.goto("/login/");
    await page.getByLabel(/Email or username/i).fill("diptu@ecolens.com");
    await page.locator('input[name="password"]').fill("Hello123");
    await page.getByTestId("login-submit").click();
    await page.waitForURL(/\/dashboard\/home/);
    // The topbar profile chip's accessible name reflects the signed-in user.
    const chip = page.getByTestId("profile-chip");
    await expect(chip).toBeVisible();
    await expect(chip).toHaveAttribute("aria-label", "Diptu");
    await expect(chip).toContainText("DI");
  });
});

test.describe("/signup", () => {
  test("renders form with 5 fields + Create Account", async ({ page }) => {
    await page.goto("/signup/");
    await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
    await expect(page.getByLabel("Full name")).toBeVisible();
    await expect(page.getByLabel("Work email")).toBeVisible();
    await expect(page.getByLabel("Company name")).toBeVisible();
    await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Confirm password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Create Account" })).toBeVisible();
  });

  test("'Login' link goes to /login", async ({ page }) => {
    await page.goto("/signup/");
    await page.getByRole("link", { name: "Login" }).click();
    await page.waitForURL(/\/login/);
  });

  test("left panel shows Measure/Reduce/Report/Improve", async ({ page }) => {
    await page.goto("/signup/");
    await expect(page.getByText("Measure").first()).toBeVisible();
    await expect(page.getByText("Reduce").first()).toBeVisible();
    await expect(page.getByText("Report").first()).toBeVisible();
    await expect(page.getByText("Improve").first()).toBeVisible();
  });
});

test.describe("/forgot-password", () => {
  test("renders email form + Send Reset Link + back link", async ({ page }) => {
    await page.goto("/forgot-password/");
    await expect(page.getByRole("heading", { name: "Forgot Password" })).toBeVisible();
    await expect(page.getByLabel("Work email")).toBeVisible();
    await expect(page.getByRole("button", { name: "Send Reset Link" })).toBeVisible();
  });

  test("'Back to Login' link goes to /login", async ({ page }) => {
    await page.goto("/forgot-password/");
    await page.getByRole("link", { name: "Back to Login" }).click();
    await page.waitForURL(/\/login/);
  });
});

test.describe("/reset-password", () => {
  test("renders 3-step indicator + password fields", async ({ page }) => {
    await page.goto("/reset-password/");
    await expect(page.getByRole("heading", { name: "Reset Password" })).toBeVisible();
    await expect(page.getByText("Verify", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("New Password", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Confirm", { exact: true }).first()).toBeVisible();
    await expect(page.getByLabel("New password", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Confirm new password", { exact: true })).toBeVisible();
    await expect(page.getByText("At least 8 characters")).toBeVisible();
    await expect(page.getByText("One uppercase letter")).toBeVisible();
    await expect(page.getByText("One number")).toBeVisible();
    await expect(page.getByText("One special character")).toBeVisible();
    await expect(page.getByRole("button", { name: "Reset Password" })).toBeVisible();
  });
});

test.describe("/verify-email", () => {
  test("renders the email + Resend + back link", async ({ page }) => {
    await page.goto("/verify-email/");
    await expect(page.getByRole("heading", { name: "Verify Your Email" })).toBeVisible();
    await expect(page.getByText("diptu.alam@company.com")).toBeVisible();
    await expect(page.getByRole("button", { name: /Resend/ })).toBeVisible();
  });
});

test.describe("/onboarding", () => {
  test("renders 6 steps on the left + Organization form on right", async ({ page }) => {
    await page.goto("/onboarding/");
    await expect(page.getByText("Step 1 of 6")).toBeVisible();
    await expect(page.getByText("Organization", { exact: true }).first()).toBeVisible();
    await expect(page.getByLabel("Organization name")).toBeVisible();
    await expect(page.getByLabel("Industry")).toBeVisible();
    await expect(page.getByLabel("Country / Region")).toBeVisible();
    await expect(page.getByLabel("Organization size")).toBeVisible();
    await expect(page.getByRole("button", { name: "Next" })).toBeVisible();
  });

  test("Next advances the wizard and shows the right step", async ({ page }) => {
    await page.goto("/onboarding/");
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText("Step 2 of 6")).toBeVisible();
    await expect(page.getByLabel("Primary operations")).toBeVisible();
  });

  test("Back button is disabled on step 1", async ({ page }) => {
    await page.goto("/onboarding/");
    const back = page.getByRole("button", { name: "Back" });
    await expect(back).toBeDisabled();
  });

  test("can navigate all 6 steps", async ({ page }) => {
    await page.goto("/onboarding/");
    for (let i = 1; i < 6; i++) {
      await expect(page.getByText(`Step ${i} of 6`)).toBeVisible();
      await page.getByRole("button", { name: "Next" }).click();
    }
    await expect(page.getByText("Step 6 of 6")).toBeVisible();
    await expect(page.getByRole("button", { name: "Finish Setup" })).toBeVisible();
  });
});

test.describe("core web vitals (auth)", () => {
  test("login: FCP < 1.5s, CLS = 0", async ({ page }) => {
    await page.goto("/login/");
    const metrics = await page.evaluate(
      () =>
        new Promise<{ fcp: number; cls: number }>((resolve) => {
          let fcp = 0;
          let cls = 0;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              if (entry.name === "first-contentful-paint") fcp = entry.startTime;
            }
          }).observe({ type: "paint", buffered: true });
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              if (!(entry as PerformanceEntry & { hadRecentInput?: boolean }).hadRecentInput) {
                cls += (entry as PerformanceEntry & { value: number }).value;
              }
            }
          }).observe({ type: "layout-shift", buffered: true });
          setTimeout(() => resolve({ fcp, cls }), 500);
        }),
    );
    expect(metrics.fcp).toBeGreaterThan(0);
    expect(metrics.fcp).toBeLessThan(1500);
    expect(metrics.cls).toBe(0);
  });
});
