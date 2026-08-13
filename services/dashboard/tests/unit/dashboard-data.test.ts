/**
 * Unit tests for the dashboard data layer.
 * Confirms shape of KPIs, tables, and lists used by /dashboard/* pages.
 */
import { describe, it, expect } from "vitest";
import {
  HOME_KPIS,
  HOME_SCOPES,
  ACTIONS_KPIS,
  ACTION_RECOMMENDATIONS,
  ACTION_OVERVIEW,
  ROADMAP,
  ANALYTICS_KPIS,
  ANALYTICS_OPPORTUNITIES,
  GOALS_KPIS,
  GOAL_ROADMAP_DATA,
  YOUR_GOALS,
  GOAL_TYPES,
  UPCOMING_DEADLINES,
  MILESTONES,
  SOURCES_KPIS,
  DATA_SOURCES,
  SOURCE_HEALTH,
  NOTIFICATIONS_KPIS,
  NOTIFICATION_LIST,
  REPORTS_KPIS,
  REPORT_TYPES,
  RECENT_REPORTS,
  SCENARIOS_KPIS,
  SCENARIOS_LIST,
  SCENARIO_TEMPLATES,
  ORG_OVERVIEW,
  ORG_LOCATIONS,
  ORG_FACILITIES,
  ORG_EMPLOYEES,
  ORG_FRAMEWORKS,
  PROFILE_USER,
  PROFILE_PREFERENCES,
  PROFILE_NOTIFICATION_CATEGORIES,
} from "@/lib/data";

describe("dashboard data", () => {
  it("every KPI list has at least 3 entries with label + value", () => {
    const kpiLists = [HOME_KPIS, ACTIONS_KPIS, ANALYTICS_KPIS, GOALS_KPIS, SOURCES_KPIS, NOTIFICATIONS_KPIS, REPORTS_KPIS, SCENARIOS_KPIS];
    for (const list of kpiLists) {
      expect(list.length).toBeGreaterThanOrEqual(3);
      for (const k of list) {
        expect(k.label).toBeTruthy();
        expect(k.value).toBeTruthy();
      }
    }
  });

  it("HOME_SCOPES totals 100%", () => {
    const total = HOME_SCOPES.reduce((s, x) => s + x.percent, 0);
    expect(total).toBe(100);
  });

  it("ACTION_OVERVIEW totals equal the sum of its parts", () => {
    const { total, recommended, inProgress, notStarted, completed } = ACTION_OVERVIEW;
    expect(total).toBe(recommended + inProgress + notStarted + completed);
  });

  it("ACTION_RECOMMENDATIONS has 6 entries with valid difficulty", () => {
    expect(ACTION_RECOMMENDATIONS).toHaveLength(6);
    for (const r of ACTION_RECOMMENDATIONS) {
      expect(["Low", "Medium", "High"]).toContain(r.difficulty);
      expect(["Low", "Medium", "High"]).toContain(r.priority);
      expect(typeof r.reduction).toBe("number");
      expect(r.reduction).toBeGreaterThan(0);
    }
  });

  it("ROADMAP has 3 phases (short / mid / long term)", () => {
    expect(ROADMAP).toHaveLength(3);
    for (const r of ROADMAP) {
      expect(r.phase).toMatch(/Term/);
      expect(r.items.length).toBeGreaterThan(0);
    }
  });

  it("ANALYTICS_OPPORTUNITIES percent totals 57% (matches the table)", () => {
    const total = ANALYTICS_OPPORTUNITIES.reduce((s, o) => s + o.percent, 0);
    expect(total).toBe(57);
  });

  it("GOAL_ROADMAP_DATA has 8 yearly labels", () => {
    expect(GOAL_ROADMAP_DATA.labels).toHaveLength(8);
    expect(GOAL_ROADMAP_DATA.actual).toHaveLength(8);
    expect(GOAL_ROADMAP_DATA.target).toHaveLength(8);
    expect(GOAL_ROADMAP_DATA.baseline).toHaveLength(8);
  });

  it("YOUR_GOALS has 6 entries with valid status", () => {
    expect(YOUR_GOALS).toHaveLength(6);
    for (const g of YOUR_GOALS) {
      expect(["On Track", "At Risk", "Behind", "Completed"]).toContain(g.status);
      expect(g.progress).toBeGreaterThanOrEqual(0);
      expect(g.progress).toBeLessThanOrEqual(100);
    }
  });

  it("GOAL_TYPES totals 100%", () => {
    const total = GOAL_TYPES.reduce((s, t) => s + t.percent, 0);
    expect(total).toBe(100);
  });

  it("UPCOMING_DEADLINES has 3 entries with daysLeft > 0", () => {
    expect(UPCOMING_DEADLINES).toHaveLength(3);
    for (const d of UPCOMING_DEADLINES) {
      expect(d.daysLeft).toBeGreaterThan(0);
    }
  });

  it("MILESTONES has 5 entries (3 completed/upcoming + 1 on track + 1 upcoming)", () => {
    expect(MILESTONES).toHaveLength(5);
  });

  it("DATA_SOURCES has 11 entries with valid status", () => {
    expect(DATA_SOURCES).toHaveLength(11);
    for (const s of DATA_SOURCES) {
      expect(["Active", "Inactive", "Syncing"]).toContain(s.status);
      expect(typeof s.dataPoints).toBe("number");
    }
  });

  it("SOURCE_HEALTH healthy + syncing + inactive sums to total", () => {
    const { healthy, syncing, inactive } = SOURCE_HEALTH;
    expect(healthy + syncing + inactive).toBe(11);
  });

  it("NOTIFICATION_LIST has 10 entries with valid priority", () => {
    expect(NOTIFICATION_LIST).toHaveLength(10);
    for (const n of NOTIFICATION_LIST) {
      expect(["High", "Medium", "Low"]).toContain(n.priority);
    }
  });

  it("REPORT_TYPES has 8 types with non-empty names", () => {
    expect(REPORT_TYPES).toHaveLength(8);
    for (const t of REPORT_TYPES) {
      expect(t.name).toBeTruthy();
      expect(t.cta).toBeTruthy();
    }
  });

  it("RECENT_REPORTS has 8 entries all completed", () => {
    expect(RECENT_REPORTS).toHaveLength(8);
    for (const r of RECENT_REPORTS) {
      expect(r.status).toBe("Completed");
      expect(r.size).toMatch(/MB/);
    }
  });

  it("SCENARIOS_LIST has 7 entries with valid status", () => {
    expect(SCENARIOS_LIST).toHaveLength(7);
    for (const s of SCENARIOS_LIST) {
      expect(["Projected", "In Progress", "Completed", "Draft"]).toContain(s.status);
      expect(s.roi).toMatch(/x$/);
    }
  });

  it("SCENARIO_TEMPLATES has 5 entries", () => {
    expect(SCENARIO_TEMPLATES).toHaveLength(5);
  });

  it("ORG_OVERVIEW has required fields", () => {
    expect(ORG_OVERVIEW.name).toBeTruthy();
    expect(ORG_OVERVIEW.employees).toBeGreaterThan(0);
    expect(ORG_OVERVIEW.locations).toBeGreaterThan(0);
  });

  it("ORG_LOCATIONS has 5 entries with valid types", () => {
    expect(ORG_LOCATIONS).toHaveLength(5);
    for (const l of ORG_LOCATIONS) {
      expect(["Headquarters", "Regional Office", "Office"]).toContain(l.type);
    }
  });

  it("ORG_FACILITIES has 4 entries with floor area", () => {
    expect(ORG_FACILITIES).toHaveLength(4);
    for (const f of ORG_FACILITIES) {
      expect(f.area).toMatch(/ft²/);
    }
  });

  it("ORG_EMPLOYEES breakdown totals 100%", () => {
    const total = ORG_EMPLOYEES.breakdown.reduce((s, e) => s + e.percent, 0);
    expect(total).toBe(100);
    expect(ORG_EMPLOYEES.breakdown.reduce((s, e) => s + e.value, 0)).toBe(ORG_EMPLOYEES.total);
  });

  it("ORG_FRAMEWORKS has 5 entries with one primary", () => {
    expect(ORG_FRAMEWORKS).toHaveLength(5);
    const primary = ORG_FRAMEWORKS.filter((f) => f.primary);
    expect(primary).toHaveLength(1);
  });

  it("PROFILE_USER has email and role", () => {
    expect(PROFILE_USER.email).toContain("@");
    expect(PROFILE_USER.role).toBeTruthy();
  });

  it("PROFILE_PREFERENCES has 6 entries", () => {
    expect(PROFILE_PREFERENCES).toHaveLength(6);
  });

  it("PROFILE_NOTIFICATION_CATEGORIES has 6 entries", () => {
    expect(PROFILE_NOTIFICATION_CATEGORIES).toHaveLength(6);
  });
});
