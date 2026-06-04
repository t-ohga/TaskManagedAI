import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type Theme,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
  THEME_VALUES,
  applyTheme,
  isTheme,
  readStoredTheme,
  resolveTheme
} from "@/lib/theme";

// M-2 (ADR-00047): theme pure module の logic。

describe("isTheme / THEME_VALUES", () => {
  it("light/dark/system のみ true", () => {
    expect(isTheme("light")).toBe(true);
    expect(isTheme("dark")).toBe(true);
    expect(isTheme("system")).toBe(true);
    expect(isTheme("blue")).toBe(false);
    expect(isTheme(null)).toBe(false);
    expect(isTheme(undefined)).toBe(false);
  });

  it("THEME_VALUES は 3 値", () => {
    expect([...THEME_VALUES]).toEqual(["light", "dark", "system"]);
  });
});

describe("resolveTheme", () => {
  it("light/dark は OS 設定に依らずそのまま", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("light", false)).toBe("light");
    expect(resolveTheme("dark", true)).toBe("dark");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("system は OS preference に従う", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
});

describe("readStoredTheme", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("保存値が有効ならそれを返す", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readStoredTheme()).toBe("dark");
  });

  it("無効値 / 未保存は system に倒す (fail-safe)", () => {
    expect(readStoredTheme()).toBe("system");
    localStorage.setItem(THEME_STORAGE_KEY, "neon");
    expect(readStoredTheme()).toBe("system");
  });

  it("localStorage アクセサ自体が throw (SecurityError) しても system に倒す (Codex F-G7)", () => {
    // Cookie/storage がポリシーで拒否される設定では `getItem` 以前に localStorage プロパティ取得が
    // throw し得る。try 外で評価すると mount 時に例外が漏れる。
    const original = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new Error("SecurityError: storage access denied");
      }
    });
    try {
      expect(readStoredTheme()).toBe("system");
    } finally {
      if (original) Object.defineProperty(globalThis, "localStorage", original);
    }
  });
});

describe("applyTheme", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
  });

  it("dark で `.dark` を付け、light で外す", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("system は matchMedia の結果に従う", () => {
    const spy = vi.spyOn(window, "matchMedia").mockImplementation(
      (q: string) => ({ matches: true, media: q }) as MediaQueryList
    );
    applyTheme("system");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    spy.mockReturnValue({ matches: false, media: "" } as MediaQueryList);
    applyTheme("system");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    spy.mockRestore();
  });
});

describe("THEME_INIT_SCRIPT (inline no-FOUC、固定文字列)", () => {
  it("storage key を literal 化し localStorage + matchMedia + classList.toggle('dark') を含む", () => {
    expect(THEME_INIT_SCRIPT).toContain('"theme"');
    expect(THEME_INIT_SCRIPT).toContain("localStorage.getItem");
    expect(THEME_INIT_SCRIPT).toContain("prefers-color-scheme: dark");
    expect(THEME_INIT_SCRIPT).toContain('classList.toggle("dark"');
    // try/catch で localStorage 不可でも壊れない。
    expect(THEME_INIT_SCRIPT).toContain("try{");
    expect(THEME_INIT_SCRIPT).toContain("catch");
  });

  it("印刷は常に light: beforeprint で .dark を外し afterprint で戻す (D-4)", () => {
    expect(THEME_INIT_SCRIPT).toContain('addEventListener("beforeprint"');
    expect(THEME_INIT_SCRIPT).toContain('addEventListener("afterprint"');
    expect(THEME_INIT_SCRIPT).toContain('classList');
  });

  it("ユーザ入力を埋め込まない (CSP hash 可能、固定)。実行しても例外を投げない", () => {
    // 固定文字列であること (テンプレートに動的値が混ざっていない) を簡易確認。
    expect(THEME_INIT_SCRIPT.startsWith("(function(){var k=")).toBe(true);
    // jsdom で評価しても throw しない (document.documentElement に作用、副作用は許容)。
    expect(() => {
      new Function(THEME_INIT_SCRIPT)();
    }).not.toThrow();
  });

  it("値域は Theme 3 値に閉じる (型の sanity)", () => {
    const all: Theme[] = ["light", "dark", "system"];
    expect(all.every(isTheme)).toBe(true);
  });
});
