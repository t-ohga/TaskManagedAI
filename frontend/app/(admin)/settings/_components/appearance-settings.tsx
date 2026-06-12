"use client";

import { useTheme } from "@/lib/use-theme";
import type { Theme } from "@/lib/theme";

// M-2 (ADR-00047): 「外観」= この端末の表示テーマ (ライト/ダーク/システム)。device-local preference
// であり project 設定ではない (R1 F-008、UI 上で明確に区別)。nav の cycling toggle と useTheme で state
// 共有。a11y: radiogroup + role=radio + aria-checked (R1 F-010)。

const OPTIONS: { value: Theme; label: string; description: string }[] = [
  { value: "light", label: "ライト", description: "常に明るい配色" },
  { value: "dark", label: "ダーク", description: "常に暗い配色" },
  { value: "system", label: "システム", description: "OS の設定に合わせる" }
];

export function AppearanceSettings() {
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="テーマ"
      className="grid gap-2 sm:grid-cols-3"
    >
      {OPTIONS.map((option) => {
        const selected = theme === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => setTheme(option.value)}
            className={`grid gap-1 rounded-md border px-3 py-3 text-left text-sm transition-colors outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
              selected
                ? "border-accent bg-accent/5 text-ink"
                : "border-line bg-panel text-muted-foreground hover:border-accent/40 hover:text-ink"
            }`}
          >
            <span className="font-medium">{option.label}</span>
            <span className="text-xs text-muted-foreground">{option.description}</span>
          </button>
        );
      })}
    </div>
  );
}
