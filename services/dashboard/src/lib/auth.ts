/**
 * Mock auth layer for ecoLens.
 *
 * In production this would be a real backend (e.g. Auth0, Cognito, or
 * a FastAPI endpoint with bcrypt + JWT). For the demo we keep a
 * hard-coded user list and a synchronous `signIn` that returns a
 * fake-but-shape-realistic session.
 *
 * Why client-side only?
 *  - The dashboard is a static export deployed to a CDN
 *  - There's no API service attached in the demo
 *  - The user list is deliberately tiny (one entry)
 *  - The data is fine to expose in dev/demo
 *
 * The session is persisted in `localStorage` so the dashboard
 * layout, topbar profile chip, and route guards can read it
 * without a server round-trip.
 *
 * NEVER replace this file's contents with the real auth lib
 * without also updating tests/unit/auth.test.ts and the
 * e2e/auth.spec.ts expectations.
 */

export type User = {
  /** unique handle (used for "@mentions" and as a stable id) */
  username: string;
  /** primary login identifier */
  email: string;
  /** display name shown in the topbar */
  name: string;
  /** initials used in the avatar chip (max 2 chars) */
  initials: string;
  /** role, drives nav visibility & admin endpoints */
  role: "admin" | "analyst" | "viewer";
  /** ISO 3166-1 alpha-2 country code, drives the dashboard's "region" filter */
  region: string;
};

export type AuthSession = {
  user: User;
  /** ms since epoch when the session was minted */
  issuedAt: number;
  /** ms since epoch when the session expires (8 hours) */
  expiresAt: number;
  /** opaque token; the real impl would be a signed JWT */
  token: string;
};

export type SignInFailureReason =
  | "invalid_credentials"
  | "unknown_user"
  | "expired"
  | "malformed";

export type SignInResult =
  | { ok: true; session: AuthSession }
  | { ok: false; reason: SignInFailureReason };

const SESSION_TTL_MS = 8 * 60 * 60 * 1000; // 8 hours
const SESSION_STORAGE_KEY = "ecolens.session";

/**
 * The dummy test user. The user asked for username `diptu`,
 * password `Hello123`.
 *
 * ⚠️ This is a demo-only file. In production, NEVER store
 * plaintext passwords in source code (or anywhere in the repo).
 */
export const MOCK_USERS: Array<User & { password: string }> = [
  {
    username: "diptu",
    email: "diptu@ecolens.com",
    name: "Diptu",
    initials: "DI",
    role: "admin",
    region: "AU",
    password: "Hello123",
  },
  {
    // A second test account for multi-user tests (e2e)
    username: "demo",
    email: "demo@ecolens.app",
    name: "Demo User",
    initials: "DU",
    role: "analyst",
    region: "AU",
    password: "demo1234",
  },
  {
    // Extra admin demo user for ad-hoc testing (promoted to admin 2026-07-28
    // per user request — to use as the primary admin login for the dashboard
    // admin panel exploration)
    username: "diptu.app",
    email: "diptu@ecolens.app",
    name: "Diptu (admin)",
    initials: "DA",
    role: "admin",
    region: "AU",
    password: "Hello123",
  },
];

/**
 * Find a user by email OR username (case-insensitive).
 * Returns the record (with password) or undefined.
 */
export function findUser(identifier: string): (User & { password: string }) | undefined {
  const needle = identifier.trim().toLowerCase();
  if (!needle) return undefined;
  return MOCK_USERS.find(
    (u) => u.email.toLowerCase() === needle || u.username.toLowerCase() === needle,
  );
}

/**
 * Validate credentials. Returns the session on success, or a typed
 * failure reason on error. Deliberately synchronous so the UI can
 * stay client-side without an API round-trip.
 *
 * Tiny artificial delay so the spinner actually shows in tests.
 */
export async function signIn(
  identifier: string,
  password: string,
  options: { delayMs?: number } = {},
): Promise<SignInResult> {
  const delay = options.delayMs ?? 250;
  await new Promise((resolve) => setTimeout(resolve, delay));

  if (!identifier || !password) {
    return { ok: false, reason: "malformed" };
  }

  const user = findUser(identifier);
  if (!user) {
    return { ok: false, reason: "unknown_user" };
  }
  if (user.password !== password) {
    return { ok: false, reason: "invalid_credentials" };
  }

  const now = Date.now();
  const session: AuthSession = {
    user: {
      username: user.username,
      email: user.email,
      name: user.name,
      initials: user.initials,
      role: user.role,
      region: user.region,
    },
    issuedAt: now,
    expiresAt: now + SESSION_TTL_MS,
    token: `mock.${user.username}.${now.toString(36)}`,
  };
  return { ok: true, session };
}

/**
 * Persist a session to localStorage. Returns the session for chaining.
 */
export function persistSession(session: AuthSession): AuthSession {
  if (typeof window === "undefined") return session;
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch {
    // localStorage can be disabled (private mode, quota) — fail silently
  }
  return session;
}

/**
 * Read the persisted session, or null if missing/expired/invalid.
 * Server-safe: returns null when called during SSR.
 */
export function readSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  let session: AuthSession;
  try {
    session = JSON.parse(raw) as AuthSession;
  } catch {
    return null;
  }
  if (!session || !session.user || !session.expiresAt) return null;
  if (Date.now() > session.expiresAt) {
    // Expired — clean up
    try {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // ignore
    }
    return null;
  }
  return session;
}

/**
 * Clear the persisted session. Idempotent.
 */
export function clearSession(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // ignore
  }
}

/**
 * Human-readable error reason. The UI uses this for inline messaging.
 */
export function reasonText(reason: SignInFailureReason): string {
  switch (reason) {
    case "invalid_credentials":
      return "That password doesn't match. Try again or reset it.";
    case "unknown_user":
      return "We couldn't find an account with that email or username.";
    case "expired":
      return "Your session has expired. Please sign in again.";
    case "malformed":
      return "Please enter both an email/username and a password.";
    default:
      return "Sign-in failed. Please try again.";
  }
}
