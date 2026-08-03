/**
 * Tests for the real (IAM-backed) auth layer in src/lib/auth.ts.
 *
 * `fetch` is mocked per-test rather than hitting a real IAM instance —
 * these are unit tests for the request/response mapping, not an
 * integration test of the backend itself (see e2e/auth.spec.ts for the
 * behavior that actually needs a live IAM + Postgres).
 *
 * NOTE: jsdom (Vitest's default in this project) provides localStorage,
 * so persist/read/clear all work in tests.
 */
import { afterEach, describe, it, expect, vi, beforeEach } from "vitest";

import {
  clearSession,
  googleSignIn,
  persistSession,
  reasonText,
  readSession,
  signIn,
  signUp,
  signUpReasonText,
  type AuthSession,
} from "@/lib/auth";

const STORAGE_KEY = "ecolens.session";

const IAM_USER = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "diptu@ecolens.app",
  first_name: "Diptu",
  last_name: "Alam",
  is_superuser: true,
  home_location: null,
};

const IAM_TOKEN_PAIR = {
  access_token: "access.jwt.token",
  refresh_token: "refresh.jwt.token",
  token_type: "bearer",
  expires_in: 1800,
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("signIn", () => {
  it("succeeds with the right credentials", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, IAM_TOKEN_PAIR)) // /auth/login
      .mockResolvedValueOnce(jsonResponse(200, IAM_USER)); // /auth/me

    const r = await signIn("diptu@ecolens.app", "Hello123!");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.session.user.username).toBe("diptu");
      expect(r.session.user.email).toBe("diptu@ecolens.app");
      expect(r.session.user.name).toBe("Diptu Alam");
      expect(r.session.user.initials).toBe("DA");
      expect(r.session.user.role).toBe("admin");
      expect(r.session.token).toBe("access.jwt.token");
      expect(r.session.refreshToken).toBe("refresh.jwt.token");
      expect(r.session.expiresAt).toBeGreaterThan(Date.now());
    }

    const [loginUrl, loginInit] = fetchMock.mock.calls[0]!;
    expect(String(loginUrl)).toMatch(/\/auth\/login$/);
    expect(JSON.parse((loginInit as RequestInit).body as string)).toEqual({
      email: "diptu@ecolens.app",
      password: "Hello123!",
    });
  });

  it("returns a generic invalid_credentials reason on 401 (no user-enumeration hint)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(401, { detail: "Incorrect email or password" }),
    );
    const r = await signIn("nobody@example.com", "whatever");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid_credentials");
  });

  it("maps 403 'not verified' to email_not_verified", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(403, { detail: "Email is not verified" }),
    );
    const r = await signIn("diptu@ecolens.app", "Hello123!");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("email_not_verified");
  });

  it("maps 403 (otherwise) to account_disabled", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(403, { detail: "Account is disabled" }),
    );
    const r = await signIn("diptu@ecolens.app", "Hello123!");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("account_disabled");
  });

  it("maps 429 to rate_limited", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(429, { detail: "Too many failed login attempts. Try again later." }),
    );
    const r = await signIn("diptu@ecolens.app", "Hello123!");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("rate_limited");
  });

  it("rejects empty identifier or password without calling fetch", async () => {
    const fetchMock = vi.mocked(fetch);
    const a = await signIn("", "Hello123!");
    expect(a.ok).toBe(false);
    if (!a.ok) expect(a.reason).toBe("malformed");
    const b = await signIn("diptu@ecolens.app", "");
    expect(b.ok).toBe(false);
    if (!b.ok) expect(b.reason).toBe("malformed");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns network_error when fetch rejects", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const r = await signIn("diptu@ecolens.app", "Hello123!");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("network_error");
  });

  it("never returns the password on the session object", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(200, IAM_TOKEN_PAIR))
      .mockResolvedValueOnce(jsonResponse(200, IAM_USER));
    const r = await signIn("diptu@ecolens.app", "Hello123!");
    if (r.ok) {
      expect(JSON.stringify(r.session)).not.toContain("Hello123");
    }
  });
});

describe("googleSignIn", () => {
  it("posts the id_token and maps the resulting session", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, IAM_TOKEN_PAIR))
      .mockResolvedValueOnce(jsonResponse(200, IAM_USER));

    const r = await googleSignIn("fake.google.id-token");
    expect(r.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/auth\/google$/);
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      id_token: "fake.google.id-token",
    });
  });

  it("surfaces a 401 as invalid_credentials", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(401, { detail: "Invalid Google ID token" }),
    );
    const r = await googleSignIn("bad-token");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("invalid_credentials");
  });
});

describe("signUp", () => {
  it("posts the split first/last name + email + password", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(201, IAM_USER));

    const r = await signUp({
      email: "new.user@example.com",
      password: "SuperSecret1",
      firstName: "New",
      lastName: "User",
    });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.email).toBe("new.user@example.com");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toMatch(/\/auth\/signup$/);
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      email: "new.user@example.com",
      password: "SuperSecret1",
      first_name: "New",
      last_name: "User",
    });
  });

  it("maps 409 to email_taken", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(409, { detail: "A user with this email already exists" }),
    );
    const r = await signUp({
      email: "diptu@ecolens.app",
      password: "SuperSecret1",
      firstName: "Diptu",
      lastName: "Alam",
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("email_taken");
  });

  it("rejects a too-short password without calling fetch", async () => {
    const fetchMock = vi.mocked(fetch);
    const r = await signUp({
      email: "x@example.com",
      password: "short",
      firstName: "X",
      lastName: "Y",
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("malformed");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects missing fields without calling fetch", async () => {
    const fetchMock = vi.mocked(fetch);
    const r = await signUp({ email: "", password: "", firstName: "", lastName: "" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("malformed");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("persistSession / readSession / clearSession", () => {
  const fake: AuthSession = {
    user: {
      username: "diptu",
      email: "diptu@ecolens.app",
      name: "Diptu Alam",
      initials: "DA",
      role: "admin",
      region: "AU",
    },
    issuedAt: Date.now(),
    expiresAt: Date.now() + 60_000,
    token: "test",
    refreshToken: "test-refresh",
  };

  it("persists and reads a session round-trip", () => {
    persistSession(fake);
    const got = readSession();
    expect(got?.user.username).toBe("diptu");
    expect(got?.token).toBe("test");
    expect(got?.refreshToken).toBe("test-refresh");
  });

  it("returns null when nothing is stored", () => {
    expect(readSession()).toBeNull();
  });

  it("returns null and clears an expired session", () => {
    const expired: AuthSession = { ...fake, expiresAt: Date.now() - 5_000 };
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
    const reasons = [
      "invalid_credentials",
      "account_disabled",
      "email_not_verified",
      "mfa_required",
      "rate_limited",
      "malformed",
      "network_error",
    ] as const;
    for (const r of reasons) {
      const text = reasonText(r);
      expect(text.length).toBeGreaterThan(0);
    }
  });
});

describe("signUpReasonText", () => {
  it("returns a non-empty string for every reason", () => {
    for (const r of ["email_taken", "malformed", "network_error"] as const) {
      const text = signUpReasonText(r);
      expect(text.length).toBeGreaterThan(0);
    }
  });
});
