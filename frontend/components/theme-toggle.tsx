"use client";

import { useCallback, useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    // localStorage は SSR で読めないため、hydration 後の effect で保存済テーマを反映する
    // (initializer で読むと server="system" と client=stored で hydration mismatch になる)。
    const stored = localStorage.getItem("theme") as Theme | null;
    if (stored) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setTheme(stored);
      applyTheme(stored);
    } else {
      applyTheme("system");
    }
  }, []);

  const toggle = useCallback(() => {
    const next: Theme = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
    setTheme(next);
    localStorage.setItem("theme", next);
    applyTheme(next);
  }, [theme]);

  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded-md border border-line px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-slate-50 hover:text-ink"
      title={`テーマ: ${theme === "light" ? "ライト" : theme === "dark" ? "ダーク" : "システム"}`}
    >
      {theme === "light" ? "☀" : theme === "dark" ? "☾" : "⚙"}
    </button>
  );
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else if (theme === "light") {
    root.classList.remove("dark");
  } else {
    const prefersDark =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (prefersDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }
}
