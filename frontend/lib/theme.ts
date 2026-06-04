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
// localStorage + matchMedia を読んで `.dark` を適用する。さらに **印刷は常に light** にするため
// beforeprint で `.dark` を一時的に外し afterprint で戻す (ADR-00047 D-4 / R2 F-002: print の
// token reset だけでは `dark:bg-amber-950/40` 等の utility variant が `.dark` 残存で dark 印刷される。
// class を外せば token surface も utility variant も両方 light 印刷になる)。
// **固定文字列 (ユーザ入力の埋め込みなし)** のため、将来 CSP は hash-based で許可できる (R1 F-009)。
export const THEME_INIT_SCRIPT =
  "(function(){var k=" +
  JSON.stringify(THEME_STORAGE_KEY) +
  ';var t="system";' +
  // storage 読込のみを try で囲む。失敗 (private mode 等) しても t="system" のまま下の matchMedia 評価へ
  // 進み、OS ダーク preference を適用する (Codex App F-G1: storage 失敗で全 try を抜けると OS ダークでも
  // light のままだった)。
  "try{var s=localStorage.getItem(k);" +
  'if(s==="light"||s==="dark"||s==="system"){t=s;}}catch(e){}' +
  "try{" +
  'var d=t==="dark"||(t==="system"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);' +
  'document.documentElement.classList.toggle("dark",d);' +
  "}catch(e){}" +
  "try{var wasDark=false;" +
  'window.addEventListener("beforeprint",function(){var c=document.documentElement.classList;wasDark=c.contains("dark");c.remove("dark");});' +
  'window.addEventListener("afterprint",function(){if(wasDark)document.documentElement.classList.add("dark");});' +
  "}catch(e){}})();";
