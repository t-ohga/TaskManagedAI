import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/components/theme-toggle";
import { AppearanceSettings } from "@/app/(admin)/settings/_components/appearance-settings";
import { THEME_STORAGE_KEY } from "@/lib/theme";

// M-2 (ADR-00047): nav toggle と設定 selector が useTheme で state 共有する (R1 F-002)。

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

afterEach(() => {
  localStorage.clear();
});

describe("ThemeToggle (nav cycling)", () => {
  it("クリックで light→dark→system→light と循環し localStorage + classList を更新する", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle />);
    const button = screen.getByRole("button");
    // 初期は light (effect で反映)。
    expect(button.getAttribute("aria-label")).toContain("現在: ライト");

    fireEvent.click(button); // -> dark
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(screen.getByRole("button").getAttribute("aria-label")).toContain("現在: ダーク");

    fireEvent.click(screen.getByRole("button")); // -> system
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");

    fireEvent.click(screen.getByRole("button")); // -> light
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("accessible name に現在テーマを含み、emoji は aria-hidden", () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-label");
    // emoji span は aria-hidden。
    const hidden = button.querySelector('[aria-hidden="true"]');
    expect(hidden).not.toBeNull();
  });
});

describe("AppearanceSettings (設定 3 択 radiogroup)", () => {
  it("radiogroup + role=radio で 3 択を描画し、選択で aria-checked + localStorage 更新", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "system");
    render(<AppearanceSettings />);
    expect(screen.getByRole("radiogroup", { name: "テーマ" })).toBeInTheDocument();
    const dark = screen.getByRole("radio", { name: /ダーク/ });
    fireEvent.click(dark);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

describe("nav toggle ↔ 設定 selector 同期 (useTheme)", () => {
  it("設定で dark を選ぶと nav toggle の表示も dark に追従する (同一 tab custom event)", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(
      <>
        <ThemeToggle />
        <AppearanceSettings />
      </>
    );
    // 設定 selector で「ダーク」を選択。
    fireEvent.click(screen.getByRole("radio", { name: /ダーク/ }));
    // nav toggle の accessible name が dark に追従。
    expect(screen.getByRole("button").getAttribute("aria-label")).toContain("現在: ダーク");
    expect(screen.getByRole("radio", { name: /ダーク/ })).toHaveAttribute("aria-checked", "true");
  });

  it("nav toggle で切り替えると設定 selector の選択も追従する", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(
      <>
        <ThemeToggle />
        <AppearanceSettings />
      </>
    );
    fireEvent.click(screen.getByRole("button")); // light -> dark
    expect(screen.getByRole("radio", { name: /ダーク/ })).toHaveAttribute("aria-checked", "true");
  });
});
