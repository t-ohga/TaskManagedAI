"use client";

import { useTheme } from "@/lib/use-theme";
import type { Theme } from "@/lib/theme";

// M-2 (ADR-00047): nav header の compact テーマ切替。設定ページの 3 択 selector と useTheme で state を
// 共有する (どちらで変えても即同期、R1 F-002)。localStorage 直接操作は useTheme に集約。

const THEME_LABEL: Record<Theme, string> = {
  light: "ライト",
  dark: "ダーク",
  system: "システム"
};

const THEME_ICON: Record<Theme, string> = {
  light: "☀",
  dark: "☾",
  system: "⚙"
};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next: Theme = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      // a11y (R1 F-010): accessible name に現在テーマを含め、emoji は装飾として aria-hidden。
      aria-label={`テーマを切り替える（現在: ${THEME_LABEL[theme]}、次: ${THEME_LABEL[next]}）`}
      title={`テーマ: ${THEME_LABEL[theme]}`}
      className="rounded-md border border-line px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-ink dark:hover:bg-slate-800 dark:hover:text-ink"
    >
      <span aria-hidden="true">{THEME_ICON[theme]}</span>
    </button>
  );
}
