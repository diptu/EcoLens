/**
 * Unit tests for the anomaly-detection data layer.
 *
 * Covers the deterministic generator + the summary aggregator.
 */
import { describe, expect, it } from "vitest";

import {
  generateAnomalies,
  summarizeAnomalies,
  type Anomaly,
  type AnomalyMethod,
  type AnomalySeverity,
  type AnomalyStatus,
  type AnomalyType,
} from "@/lib/admin";

describe("generateAnomalies", () => {
  it("returns the requested number of anomalies", () => {
    expect(generateAnomalies(30)).toHaveLength(30);
    expect(generateAnomalies(5)).toHaveLength(5);
    expect(generateAnomalies(0)).toHaveLength(0);
  });

  it("is deterministic for the same inputs", () => {
    const a = generateAnomalies(20);
    const b = generateAnomalies(20);
    expect(a).toEqual(b);
  });

  it("uses all three methods (rule, ml, hybrid) across a 30-item batch", () => {
    const items = generateAnomalies(30);
    const methods = new Set(items.map((a) => a.method));
    expect(methods.has("rule")).toBe(true);
    expect(methods.has("ml")).toBe(true);
    expect(methods.has("hybrid")).toBe(true);
  });

  it("uses all three severities (high, medium, low) across a 30-item batch", () => {
    const items = generateAnomalies(30);
    const sevs = new Set(items.map((a) => a.severity));
    expect(sevs.has("high")).toBe(true);
    expect(sevs.has("medium")).toBe(true);
    expect(sevs.has("low")).toBe(true);
  });

  it("uses all four statuses (new, acknowledged, resolved, false_positive)", () => {
    const items = generateAnomalies(30);
    const statuses = new Set(items.map((a) => a.status));
    expect(statuses.size).toBeGreaterThanOrEqual(2);
  });

  it("every anomaly has a unique id", () => {
    const items = generateAnomalies(30);
    const ids = new Set(items.map((a) => a.id));
    expect(ids.size).toBe(items.length);
  });

  it("every anomaly has a numeric score in [0, 1]", () => {
    const items = generateAnomalies(30);
    for (const a of items) {
      expect(a.score).toBeGreaterThanOrEqual(0);
      expect(a.score).toBeLessThanOrEqual(1);
    }
  });

  it("every anomaly has a non-empty reason", () => {
    const items = generateAnomalies(30);
    for (const a of items) {
      expect(a.reason.length).toBeGreaterThan(20);
    }
  });

  it("returns anomalies sorted by detected_at descending (newest first)", () => {
    const items = generateAnomalies(30);
    for (let i = 1; i < items.length; i++) {
      const prev = new Date(items[i - 1]!.detected_at).getTime();
      const curr = new Date(items[i]!.detected_at).getTime();
      expect(prev).toBeGreaterThanOrEqual(curr);
    }
  });

  it("has at least one anomaly per type category over a 30-item batch", () => {
    // 30 items × 12 templates = 2.5 cycles → at least 2 per type minimum
    const items = generateAnomalies(30);
    const types = new Set(items.map((a) => a.type));
    expect(types.size).toBe(12);
  });

  it("contains a mix of regions (NEM, NSW1, …, WEM)", () => {
    const items = generateAnomalies(30);
    const regions = new Set(items.map((a) => a.region));
    expect(regions.has("WEM")).toBe(true);
    // NEM regions are also represented
    const nemRegions = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1"];
    expect(nemRegions.some((r) => regions.has(r))).toBe(true);
  });

  it("all 5 source types appear in a 30-item batch", () => {
    const items = generateAnomalies(30);
    const sources = new Set(items.map((a) => a.source));
    expect(sources.size).toBe(5);
  });
});

describe("summarizeAnomalies", () => {
  it("returns zeros for an empty input", () => {
    const s = summarizeAnomalies([]);
    expect(s.total).toBe(0);
    expect(s.new_count).toBe(0);
    expect(s.high_severity).toBe(0);
    expect(s.medium_severity).toBe(0);
    expect(s.low_severity).toBe(0);
    expect(s.hybrid_count).toBe(0);
    expect(s.rule_count).toBe(0);
    expect(s.ml_count).toBe(0);
    expect(s.avg_score).toBe(0);
    expect(s.daily_counts).toHaveLength(7);
    // Every daily count is 0
    for (const d of s.daily_counts) {
      expect(d.count).toBe(0);
    }
  });

  it("counts each status, severity, method", () => {
    const fake: Anomaly[] = [
      mkAnom("new",         "high",   "hybrid"),
      mkAnom("new",         "medium", "rule"),
      mkAnom("acknowledged","high",   "ml"),
      mkAnom("resolved",    "low",    "rule"),
      mkAnom("false_positive","low",  "ml"),
    ];
    const s = summarizeAnomalies(fake);
    expect(s.total).toBe(5);
    expect(s.new_count).toBe(2);
    expect(s.acknowledged_count).toBe(1);
    expect(s.resolved_count).toBe(1);
    expect(s.false_positive_count).toBe(1);
    expect(s.high_severity).toBe(2);
    expect(s.medium_severity).toBe(1);
    expect(s.low_severity).toBe(2);
    expect(s.hybrid_count).toBe(1);
    expect(s.rule_count).toBe(2);
    expect(s.ml_count).toBe(2);
  });

  it("averages the score", () => {
    const fake: Anomaly[] = [
      mkAnom("new", "high", "hybrid", 0.6),
      mkAnom("new", "high", "hybrid", 0.8),
      mkAnom("new", "high", "hybrid", 1.0),
    ];
    const s = summarizeAnomalies(fake);
    expect(s.avg_score).toBe(0.8);
  });

  it("returns exactly 7 daily counts (last week)", () => {
    const s = summarizeAnomalies(generateAnomalies(30));
    expect(s.daily_counts).toHaveLength(7);
    for (const d of s.daily_counts) {
      expect(d.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(d.count).toBeGreaterThanOrEqual(0);
    }
  });
});

// ────────────────────────────────────────────────────────────────────
// Test helpers
// ────────────────────────────────────────────────────────────────────

function mkAnom(
  status: AnomalyStatus,
  severity: AnomalySeverity,
  method: AnomalyMethod,
  score = 0.9,
): Anomaly {
  return {
    id: `test-${Math.random().toString(36).slice(2)}`,
    detected_at: new Date().toISOString(),
    ts: new Date().toISOString(),
    region: "NSW1",
    source: "aemo_nem",
    type: "demand_spike",
    severity,
    method,
    score,
    reason: "test reason",
    observed_value: 1,
    expected_value: 1,
    unit: "MW",
    status,
    assigned_to: null,
    notes: null,
  };
}
