/**
 * Unit tests for the admin data layer (src/lib/admin.ts).
 *
 * The functions are pure deterministic generators, so the tests
 * focus on shape + invariants:
 *  - the right kinds/counts of items are returned
 *  - values are within sane ranges
 *  - timestamps are within ±1 day of "now"
 *  - role / status values are valid
 */
import { describe, expect, it } from "vitest";

import {
  generateModelRegistry,
  generateDataSources,
  generateJobs,
  generateAdminUsers,
  generateSystemHealth,
  type JobKind,
  type JobStatus,
  type User,
} from "@/lib/admin";

const VALID_JOB_KINDS: JobKind[] = [
  "train", "fine_tune", "evaluate", "promote", "ingest", "backfill", "refresh", "archive",
];
const VALID_JOB_STATUSES: JobStatus[] = [
  "queued", "running", "succeeded", "failed", "cancelled",
];
const VALID_ROLES: User["role"][] = ["admin", "analyst", "viewer"];

describe("generateModelRegistry", () => {
  const models = generateModelRegistry();

  it("returns 3 versions", () => {
    expect(models).toHaveLength(3);
  });

  it("has exactly one Production, one Staging, one Archived", () => {
    const stages = models.map((m) => m.stage);
    expect(stages.filter((s) => s === "Production")).toHaveLength(1);
    expect(stages.filter((s) => s === "Staging")).toHaveLength(1);
    expect(stages.filter((s) => s === "Archived")).toHaveLength(1);
  });

  it("uses sequential version numbers", () => {
    const versions = models.map((m) => m.version).sort((a, b) => a - b);
    expect(versions).toEqual([5, 6, 7]);
  });

  it("all metrics are positive numbers", () => {
    for (const m of models) {
      expect(m.metrics.mape).toBeGreaterThan(0);
      expect(m.metrics.rmse_mw).toBeGreaterThan(0);
      expect(m.metrics.mae_mw).toBeGreaterThan(0);
    }
  });

  it("Production model has the lowest MAPE", () => {
    const production = models.find((m) => m.stage === "Production")!;
    const other = models.filter((m) => m.stage !== "Production");
    for (const o of other) {
      expect(production.metrics.mape).toBeLessThanOrEqual(o.metrics.mape);
    }
  });

  it("each model has a created_at within the last 100 days", () => {
    const now = Date.now();
    for (const m of models) {
      const ts = new Date(m.created_at).getTime();
      expect(ts).toBeLessThanOrEqual(now);
      expect(now - ts).toBeLessThan(100 * 86_400_000);
    }
  });
});

describe("generateDataSources", () => {
  const sources = generateDataSources();

  it("includes AEMO NEM and BoM live", () => {
    const ids = sources.map((s) => s.id);
    expect(ids).toContain("aemo-nem");
    expect(ids).toContain("bom-live");
  });

  it("uses valid cadence values", () => {
    const valid = ["5-min", "30-min", "hourly", "daily", "weekly", "yearly", "manual"];
    for (const s of sources) {
      expect(valid).toContain(s.cadence);
    }
  });

  it("uses valid type values", () => {
    const valid = ["api", "csv", "ftp", "scraper"];
    for (const s of sources) {
      expect(valid).toContain(s.type);
    }
  });

  it("at least one source is enabled", () => {
    expect(sources.some((s) => s.enabled)).toBe(true);
  });

  it("down sources have failed last_run_status", () => {
    for (const s of sources) {
      if (s.status === "down") {
        expect(s.last_run_status).toBe("failed");
      }
    }
  });

  it("healthy sources have ok last_run_status", () => {
    for (const s of sources) {
      if (s.status === "healthy") {
        expect(s.last_run_status).toBe("ok");
      }
    }
  });
});

describe("generateJobs", () => {
  it("respects the limit argument", () => {
    expect(generateJobs(5)).toHaveLength(5);
    expect(generateJobs(12)).toHaveLength(12);
  });

  it("uses valid job kinds and statuses", () => {
    const jobs = generateJobs(20);
    for (const j of jobs) {
      expect(VALID_JOB_KINDS).toContain(j.kind);
      expect(VALID_JOB_STATUSES).toContain(j.status);
    }
  });

  it("succeeded jobs have a result and a duration", () => {
    const jobs = generateJobs(20);
    for (const j of jobs) {
      if (j.status === "succeeded") {
        expect(j.result).not.toBeNull();
        expect(j.duration_seconds).not.toBeNull();
        expect(j.duration_seconds!).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("failed jobs have an error message", () => {
    const jobs = generateJobs(20);
    const failed = jobs.filter((j) => j.status === "failed");
    if (failed.length > 0) {
      for (const j of failed) {
        expect(j.error).not.toBeNull();
        expect(j.error!.length).toBeGreaterThan(0);
      }
    }
  });

  it("running jobs have progress between 0 and 1", () => {
    const jobs = generateJobs(20);
    for (const j of jobs.filter((j) => j.status === "running")) {
      expect(j.progress).toBeGreaterThan(0);
      expect(j.progress).toBeLessThanOrEqual(1);
    }
  });

  it("queued jobs have not started yet", () => {
    const jobs = generateJobs(20);
    for (const j of jobs.filter((j) => j.status === "queued")) {
      expect(j.started_at).toBeNull();
      expect(j.finished_at).toBeNull();
    }
  });

  it("all jobs have unique IDs", () => {
    const jobs = generateJobs(20);
    const ids = new Set(jobs.map((j) => j.id));
    expect(ids.size).toBe(jobs.length);
  });

  it("all jobs have log entries when not queued", () => {
    const jobs = generateJobs(20);
    for (const j of jobs.filter((j) => j.status !== "queued")) {
      expect(j.log.length).toBeGreaterThan(0);
    }
  });
});

describe("generateAdminUsers", () => {
  const users = generateAdminUsers();

  it("includes the diptu admin", () => {
    const diptu = users.find((u) => u.username === "diptu");
    expect(diptu).toBeDefined();
    expect(diptu!.email).toBe("diptu@ecolens.com");
    expect(diptu!.role).toBe("admin");
  });

  it("includes at least one admin from @ecolens.com (canonical domain)", () => {
    const admins = users.filter((u) => u.role === "admin");
    expect(admins.length).toBeGreaterThanOrEqual(1);
    const canonical = admins.find((u) => u.email.endsWith("@ecolens.com"));
    expect(canonical).toBeDefined();
  });

  it("promoted demo user (diptu@ecolens.app) is now an admin too", () => {
    const u = users.find((x) => x.email === "diptu@ecolens.app");
    expect(u).toBeDefined();
    expect(u!.role).toBe("admin");
  });

  it("uses valid roles", () => {
    for (const u of users) {
      expect(VALID_ROLES).toContain(u.role);
    }
  });

  it("usernames are unique", () => {
    const usernames = users.map((u) => u.username);
    expect(new Set(usernames).size).toBe(usernames.length);
  });

  it("emails are unique", () => {
    const emails = users.map((u) => u.email);
    expect(new Set(emails).size).toBe(emails.length);
  });

  it("at least one user per role", () => {
    expect(users.some((u) => u.role === "admin")).toBe(true);
    expect(users.some((u) => u.role === "analyst")).toBe(true);
    expect(users.some((u) => u.role === "viewer")).toBe(true);
  });
});

describe("generateSystemHealth", () => {
  const h = generateSystemHealth();

  it("status is one of healthy/degraded/down", () => {
    expect(["healthy", "degraded", "down"]).toContain(h.status);
  });

  it("has component entries", () => {
    expect(Object.keys(h.components).length).toBeGreaterThan(0);
  });

  it("postgres component is reported", () => {
    expect(h.components.postgres).toBeDefined();
    expect(h.components.postgres.status).toBe("healthy");
  });

  it("disk + memory percentages are between 0 and 100", () => {
    expect(h.disk.pct_used).toBeGreaterThanOrEqual(0);
    expect(h.disk.pct_used).toBeLessThanOrEqual(100);
    expect(h.memory.pct_used).toBeGreaterThanOrEqual(0);
    expect(h.memory.pct_used).toBeLessThanOrEqual(100);
  });

  it("recent_errors is an array", () => {
    expect(Array.isArray(h.recent_errors)).toBe(true);
  });

  it("model_loader reports the current model", () => {
    expect(h.components.model_loader.current_model).toBeDefined();
    expect(h.components.model_loader.current_model).toContain("v");
  });
});
