// M-2 (ADR-00047): テーマ (ライト/ダーク/システム) の client-safe pure module。
// hook / top-level browser API は置かない (server の root layout が `THEME_INIT_SCRIPT` を import する
// ため。plan-review R2 F-001、A-6 F-C1 と同型の RSC 境界)。hook は `lib/use-theme.ts` (`"use client"`)。
//
// 永続化は localStorage (既存 theme-toggle 踏襲、cookie 化しない → server 読込不要で root が static)。

export type Theme = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "theme";
export const THEME_VALUES: readonly Theme[] = ["light", "dark", "system"] as const;

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

/** localStorage から保存テーマを読む (無効/不在は "system")。client でのみ意味を持つ。 */
export function readStoredTheme(): Theme {
  if (typeof localStorage === "undefined") return "system";
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(value) ? value : "system";
  } catch {
    return "system";
  }
}

/** OS が dark を好むか (prefers-color-scheme)。 */
export function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

/** テーマ選択 + OS preference から実際の light/dark を解決する (pure)。 */
export function resolveTheme(theme: Theme, prefersDark: boolean): "light" | "dark" {
  if (theme === "dark") return "dark";
  if (theme === "light") return "light";
  return prefersDark ? "dark" : "light";
}

/** `<html>` の `.dark` class を現在のテーマに合わせて適用する (client only)。 */
export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  const resolved = resolveTheme(theme, systemPrefersDark());
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

// FOUC 解消用の inline blocking script。root layout の <head> で first paint 前に同期実行され、
// localStorage + matchMedia を読んで `.dark` を適用する。**固定文字列 (ユーザ入力の埋め込みなし)** の
// ため、将来 CSP を導入する場合は hash-based CSP で許可できる (plan-review R1 F-009)。
// storage key は JSON.stringify で安全に literal 化する。
export const THEME_INIT_SCRIPT =
  "(function(){try{" +
  "var k=" +
  JSON.stringify(THEME_STORAGE_KEY) +
  ";var t=localStorage.getItem(k);" +
  'if(t!=="light"&&t!=="dark"&&t!=="system"){t="system";}' +
  'var d=t==="dark"||(t==="system"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);' +
  'document.documentElement.classList.toggle("dark",d);' +
  "}catch(e){}})();";
