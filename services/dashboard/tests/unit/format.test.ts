/**
 * Unit tests for the format helpers (MotionCounter formatters).
 */
import { describe, it, expect } from "vitest";
import { formatThousands, formatCompact } from "@/components/motion/motion-counter";

describe("formatThousands", () => {
  it("formats 0", () => {
    expect(formatThousands(0)).toBe("0");
  });
  it("formats small numbers without separators", () => {
    expect(formatThousands(42)).toBe("42");
  });
  it("formats thousands with comma separator", () => {
    expect(formatThousands(1250)).toBe("1,250");
  });
  it("formats millions with comma separators", () => {
    expect(formatThousands(2400000)).toBe("2,400,000");
  });
  it("rounds non-integer values", () => {
    expect(formatThousands(1250.7)).toBe("1,251");
  });
});

describe("formatCompact", () => {
  it("formats thousands as K", () => {
    expect(formatCompact(1500)).toBe("1.5K");
  });
  it("formats millions as M", () => {
    expect(formatCompact(2400000)).toBe("2.4M");
  });
  it("formats small numbers without suffix", () => {
    expect(formatCompact(42)).toBe("42");
  });
  it("rounds thousands to 1 decimal", () => {
    expect(formatCompact(9999)).toBe("10.0K");
  });
});
