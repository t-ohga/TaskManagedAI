import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TOUR_STEPS,
  TOUR_STORAGE_KEY,
  TOUR_VERSION,
  markTourCompleted,
  progressLabel,
  readTourCompleted
} from "@/lib/feature-tour";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("TOUR_STEPS", () => {
  it("has at least 5 steps, each with title / description / href / icon", () => {
    expect(TOUR_STEPS.length).toBeGreaterThanOrEqual(5);
    for (const step of TOUR_STEPS) {
      expect(step.id).toBeTruthy();
      expect(step.title.length).toBeGreaterThan(0);
      expect(step.description.length).toBeGreaterThan(0);
      expect(step.href.startsWith("/")).toBe(true);
      expect(step.icon.length).toBeGreaterThan(0);
    }
  });

  it("has unique step ids", () => {
    const ids = TOUR_STEPS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("includes the SP-032 domain-trust step", () => {
    expect(TOUR_STEPS.some((s) => s.href === "/domain-trust")).toBe(true);
  });
});

describe("readTourCompleted / markTourCompleted", () => {
  it("returns false when nothing is stored", () => {
    expect(readTourCompleted()).toBe(false);
  });

  it("returns true after markTourCompleted (version match)", () => {
    markTourCompleted();
    expect(localStorage.getItem(TOUR_STORAGE_KEY)).toBe(TOUR_VERSION);
    expect(readTourCompleted()).toBe(true);
  });

  it("returns false for a stale version (re-show on content bump)", () => {
    localStorage.setItem(TOUR_STORAGE_KEY, "0");
    expect(readTourCompleted()).toBe(false);
  });

  it("is SecurityError-safe when getItem throws (does not crash)", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readTourCompleted()).toBe(false);
  });

  it("is SecurityError-safe when setItem throws (does not crash)", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => markTourCompleted()).not.toThrow();
  });
});

describe("progressLabel", () => {
  it("renders 1-indexed progress out of total", () => {
    expect(progressLabel(0)).toBe(`1 / ${TOUR_STEPS.length}`);
    expect(progressLabel(TOUR_STEPS.length - 1)).toBe(`${TOUR_STEPS.length} / ${TOUR_STEPS.length}`);
  });
});
