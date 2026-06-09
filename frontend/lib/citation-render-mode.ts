// SP-027 (ADR-00053): citation render mode の client-safe pure module。
// device-local UI preference (localStorage、cookie 化せず server 非依存)。M-2 (lib/theme.ts) /
// P-2 (lib/feature-tour.ts) と同じ SecurityError-safe アクセサ pattern を踏襲する
// (localStorage プロパティ取得自体が throw し得る)。
// 非監査・非権限・非契約の表示 preference (証跡 / レビュー結果の意味を変えない、R1 F-014)。

export type CitationRenderMode = "compact" | "detailed" | "provenance";

export const CITATION_RENDER_MODES: readonly CitationRenderMode[] = [
  "compact",
  "detailed",
  "provenance"
] as const;

export const CITATION_RENDER_MODE_STORAGE_KEY = "taskmanagedai.citation-render-mode";
export const DEFAULT_CITATION_RENDER_MODE: CitationRenderMode = "detailed";

export function isCitationRenderMode(value: unknown): value is CitationRenderMode {
  return value === "compact" || value === "detailed" || value === "provenance";
}

/** localStorage から render mode を読む (無効/不在は default)。SecurityError-safe。 */
export function readCitationRenderMode(): CitationRenderMode {
  try {
    const storage = globalThis.localStorage;
    if (!storage) return DEFAULT_CITATION_RENDER_MODE;
    const value = storage.getItem(CITATION_RENDER_MODE_STORAGE_KEY);
    return isCitationRenderMode(value) ? value : DEFAULT_CITATION_RENDER_MODE;
  } catch {
    return DEFAULT_CITATION_RENDER_MODE;
  }
}

/** render mode を保存する (失敗は無視)。SecurityError-safe。 */
export function writeCitationRenderMode(mode: CitationRenderMode): void {
  try {
    const storage = globalThis.localStorage;
    if (!storage) return;
    storage.setItem(CITATION_RENDER_MODE_STORAGE_KEY, mode);
  } catch {
    // storage 不可 (private mode 等) でも UI は壊さない。
  }
}

export function citationRenderModeLabel(mode: CitationRenderMode): string {
  switch (mode) {
    case "compact":
      return "簡易";
    case "detailed":
      return "詳細";
    case "provenance":
      return "来歴";
  }
}
