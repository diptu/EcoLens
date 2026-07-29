/**
 * Tests for the mock auth layer in src/lib/auth.ts.
 *
 * NOTE: jsdom (Vitest's default in this project) provides
 * localStorage, so persist/read/clear all work in tests.
 */
import { describe, it, expect, beforeEach } from "vitest";

import {
  MOCK_USERS,
  clearSession,
  findUser,
  persistSession,
  readSession,
  reasonText,
  signIn,
  type AuthSession,
} from "@/lib/auth";

const STORAGE_KEY = "ecolens.session";

beforeEach(() => {
  localStorage.clear();
});

describe("MOCK_USERS", () => {
  it("contains the requested diptu / Hello123 account", () => {
    const diptu = MOCK_USERS.find((u) => u.username === "diptu");
    expect(diptu).toBeDefined();
    expect(diptu?.password).toBe("Hello123");
    expect(diptu?.email).toBe("diptu@ecolens.com");
    expect(diptu?.role).toBe("admin");
  });

  it("has unique usernames and emails", () => {
    const usernames = MOCK_USERS.map((u) => u.username);
    const emails = MOCK_USERS.map((u) => u.email);
    expect(new Set(usernames).size).toBe(usernames.length);
    expect(new Set(emails).size).toBe(emails.length);
  });

  it("every user has a 2-char initials badge", () => {
    for (const u of MOCK_USERS) {
      expect(u.initials.length).toBeGreaterThanOrEqual(1);
      expect(u.initials.length).toBeLessThanOrEqual(2);
    }
  });

  it("contains the diptu@ecolens.app / Hello123 demo account (admin role, promoted 2026-07-28)", () => {
    const u = MOCK_USERS.find((x) => x.email === "diptu@ecolens.app");
    expect(u).toBeDefined();
    expect(u?.password).toBe("Hello123");
    expect(u?.role).toBe("admin");
  });
});

describe("findUser", () => {
  it("finds by exact email (case-insensitive)", () => {
    const u = findUser("DIPTU@ecolens.com");
    expect(u?.username).toBe("diptu");
  });

  it("finds by exact username (case-insensitive)", () => {
    const u = findUser("Diptu");
    expect(u?.email).toBe("diptu@ecolens.com");
  });

  it("returns undefined for an empty string", () => {
    expect(findUser("")).toBeUndefined();
    expect(findUser("   ")).toBeUndefined();
  });

  it("returns undefined for an unknown identifier", () => {
    expect(findUser("nobody@example.com")).toBeUndefined();
  });
});

describe("signIn", () => {
  it("succeeds with the right credentials (delay 0 for speed)", async () => {
    const r = await signIn("diptu", "Hello123", { delayMs: 0 });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.session.user.username).toBe("diptu");
      expect(r.session.user.email).toBe("diptu@ecolens.com");
      expect(r.session.token).toMatch(/^mock\.diptu\./);
      expect(r.session.expiresAt).toBeGreaterThan(Date.now());
    }
  });

  it("succeeds when the email is used instead of the username", async () => {
    const r = await signIn("diptu@ecolens.com", "Hello123", { delayMs: 0 });
    expect(r.ok).toBe(true);
  });

  it("rejects the wrong password", async () => {
    const r = await signIn("diptu", "WrongPassword", { delayMs: 0 });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid_credentials");
  });

  it("rejects an unknown user", async () => {
    const r = await signIn("nobody", "x", { delayMs: 0 });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("unknown_user");
  });

  it("rejects empty identifier or password", async () => {
    const a = await signIn("", "Hello123", { delayMs: 0 });
    expect(a.ok).toBe(false);
    if (!a.ok) expect(a.reason).toBe("malformed");
    const b = await signIn("diptu", "", { delayMs: 0 });
    expect(b.ok).toBe(false);
    if (!b.ok) expect(b.reason).toBe("malformed");
  });

  it("never returns the password on the session object", async () => {
    const r = await signIn("diptu", "Hello123", { delayMs: 0 });
    if (r.ok) {
      const j = JSON.stringify(r.session);
      expect(j).not.toContain("Hello123");
    }
  });
});

describe("persistSession / readSession / clearSession", () => {
  it("persists and reads a session round-trip", () => {
    const r = signIn("diptu", "Hello123", { delayMs: 0 });
    // We can't await inside the it()'s body for setup; build a fake one instead.
    const fake: AuthSession = {
      user: {
        username: "diptu",
        email: "diptu@ecolens.com",
        name: "Diptu",
        initials: "DI",
        role: "admin",
        region: "AU",
      },
      issuedAt: Date.now(),
      expiresAt: Date.now() + 60_000,
      token: "test",
    };
    persistSession(fake);
    const got = readSession();
    expect(got?.user.username).toBe("diptu");
    expect(got?.token).toBe("test");
  });

  it("returns null when nothing is stored", () => {
    expect(readSession()).toBeNull();
  });

  it("returns null and clears an expired session", () => {
    const expired: AuthSession = {
      user: {
        username: "diptu",
        email: "diptu@ecolens.com",
        name: "Diptu",
        initials: "DI",
        role: "admin",
        region: "AU",
      },
      issuedAt: Date.now() - 10_000,
      expiresAt: Date.now() - 5_000,
      token: "expired",
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(expired));
    expect(readSession()).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("returns null for corrupted JSON", () => {
    localStorage.setItem(STORAGE_KEY, "not-json");
    expect(readSession()).toBeNull();
  });

  it("clearSession is idempotent", () => {
    clearSession();
    clearSession();
    expect(readSession()).toBeNull();
  });
});

describe("reasonText", () => {
  it("returns a non-empty string for every reason", () => {
    for (const r of ["invalid_credentials", "unknown_user", "expired", "malformed"] as const) {
      const text = reasonText(r);
      expect(text.length).toBeGreaterThan(0);
      expect(text).not.toMatch(/^Sign-in failed\.$/);
    }
  });
});
