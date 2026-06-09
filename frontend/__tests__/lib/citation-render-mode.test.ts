import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CITATION_RENDER_MODES,
  CITATION_RENDER_MODE_STORAGE_KEY,
  DEFAULT_CITATION_RENDER_MODE,
  citationRenderModeLabel,
  isCitationRenderMode,
  readCitationRenderMode,
  writeCitationRenderMode
} from "@/lib/citation-render-mode";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("citation render mode enum", () => {
  it("has exactly compact/detailed/provenance", () => {
    expect(new Set(CITATION_RENDER_MODES)).toEqual(new Set(["compact", "detailed", "provenance"]));
  });

  it("isCitationRenderMode narrows", () => {
    expect(isCitationRenderMode("compact")).toBe(true);
    expect(isCitationRenderMode("nope")).toBe(false);
    expect(isCitationRenderMode(null)).toBe(false);
  });

  it("labels in Japanese", () => {
    expect(citationRenderModeLabel("compact")).toBe("簡易");
    expect(citationRenderModeLabel("detailed")).toBe("詳細");
    expect(citationRenderModeLabel("provenance")).toBe("来歴");
  });
});

describe("read/write render mode", () => {
  it("defaults to detailed when nothing stored", () => {
    expect(readCitationRenderMode()).toBe(DEFAULT_CITATION_RENDER_MODE);
    expect(DEFAULT_CITATION_RENDER_MODE).toBe("detailed");
  });

  it("round-trips a stored mode", () => {
    writeCitationRenderMode("provenance");
    expect(localStorage.getItem(CITATION_RENDER_MODE_STORAGE_KEY)).toBe("provenance");
    expect(readCitationRenderMode()).toBe("provenance");
  });

  it("falls back to default for invalid stored value", () => {
    localStorage.setItem(CITATION_RENDER_MODE_STORAGE_KEY, "garbage");
    expect(readCitationRenderMode()).toBe(DEFAULT_CITATION_RENDER_MODE);
  });

  it("is SecurityError-safe when getItem throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readCitationRenderMode()).toBe(DEFAULT_CITATION_RENDER_MODE);
  });

  it("is SecurityError-safe when setItem throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => writeCitationRenderMode("compact")).not.toThrow();
  });
});
