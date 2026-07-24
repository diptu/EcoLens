"use client";

/**
 * ECO-131: authentication.
 *
 * IMPORTANT -- this is a DEMO/LOCAL stand-in, not real authentication.
 * There is no auth backend anywhere in this stack (forecast-api and the
 * warehouse API are both explicitly scoped as unauthenticated, localhost
 * + nginx-TLS-only services -- see strategy.md). This context simulates
 * a session using localStorage so the login/signup/forgot-password forms
 * are functionally real (validation, loading/error states, redirects)
 * instead of inert markup, without pretending to be production-secure:
 * anyone with devtools access can forge a "session" here. There is no
 * password check, no hashing, no server round-trip.
 *
 * To swap in a real backend later: replace the three functions' bodies
 * (`login`/`signup`/`logout`) with real API calls to whatever auth
 * service gets built (see root TODO.md) -- every call site in this app
 * only depends on this module's exported hook, not on how it's
 * implemented internally.
 */
import { createContext, useCallback, useContext, useEffect, useState } from "react";

const STORAGE_KEY = "ecolens_demo_session";

export type DemoUser = { name: string; email: string };

type AuthContextValue = {
  user: DemoUser | null;
  /** True until the initial localStorage read completes (avoids a
   * hydration flash of "logged out" state on first paint). */
  loading: boolean;
  login: (email: string, password: string) => Promise<{ ok: true } | { ok: false; error: string }>;
  signup: (name: string, email: string, password: string) => Promise<{ ok: true } | { ok: false; error: string }>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function readSession(): DemoUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as DemoUser) : null;
  } catch {
    return null;
  }
}

function writeSession(user: DemoUser | null) {
  if (typeof window === "undefined") return;
  try {
    if (user) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* localStorage may be blocked (private mode); session just won't persist */
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<DemoUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // One-time hydration from localStorage (a browser-only API that
    // doesn't exist during SSR/static export) -- no lazy-initializer
    // alternative here, same as billing-toggle.tsx's identical pattern.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUser(readSession());
    setLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    // Demo-only "validation" -- see module docstring. Simulates network
    // latency so loading states in the UI are actually exercised.
    await new Promise((r) => setTimeout(r, 400));
    if (!email.includes("@")) return { ok: false as const, error: "Enter a valid email address." };
    if (password.length < 6) return { ok: false as const, error: "Password must be at least 6 characters." };
    const demoUser: DemoUser = { name: email.split("@")[0], email };
    writeSession(demoUser);
    setUser(demoUser);
    return { ok: true as const };
  }, []);

  const signup = useCallback(async (name: string, email: string, password: string) => {
    await new Promise((r) => setTimeout(r, 400));
    if (!name.trim()) return { ok: false as const, error: "Enter your name." };
    if (!email.includes("@")) return { ok: false as const, error: "Enter a valid email address." };
    if (password.length < 6) return { ok: false as const, error: "Password must be at least 6 characters." };
    const demoUser: DemoUser = { name, email };
    writeSession(demoUser);
    setUser(demoUser);
    return { ok: true as const };
  }, []);

  const logout = useCallback(() => {
    writeSession(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
