import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "@/components/theme-toggle";
import { AppearanceSettings } from "@/app/(admin)/settings/_components/appearance-settings";
import { THEME_STORAGE_KEY } from "@/lib/theme";
import { __resetSessionThemeForTest } from "@/lib/use-theme";

// M-2 (ADR-00047): nav toggle と設定 selector が useTheme で state 共有する (R1 F-002)。

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  // module-level の in-session 選択 (F-G4) を test 間でリークさせない。
  __resetSessionThemeForTest();
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

  it("別 tab の theme 変更 (StorageEvent) で controls と .dark class の両方が追従する (Codex F-D1)", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(
      <>
        <ThemeToggle />
        <AppearanceSettings />
      </>
    );
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    // 別 tab が localStorage を dark に変更 → StorageEvent を発火 (jsdom は別 tab 変更を自動発火しない)。
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    fireEvent(
      window,
      new StorageEvent("storage", { key: THEME_STORAGE_KEY, newValue: "dark" })
    );

    // controls (state) と DOM の .dark class の両方が dark に追従する (state だけでなく配色も)。
    expect(screen.getByRole("radio", { name: /ダーク/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button").getAttribute("aria-label")).toContain("現在: ダーク");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

// Codex App F-G4: localStorage が throw する環境 (private mode 等) でも、in-session の明示選択が
// 「後から mount する別 consumer」「OS preference 変更」で system に巻き戻らないこと。
describe("storage 無効環境での in-session テーマ保持 (Codex F-G4)", () => {
  // jsdom default の matchMedia 不在を test 内で制御するための最小 mock。
  // useTheme は addEventListener/removeEventListener のみ使うため legacy addListener/removeListener は省く。
  let mediaListeners: (() => void)[] = [];

  function installMatchMedia(matches: boolean): void {
    mediaListeners = [];
    window.matchMedia = ((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: (_type: string, cb: () => void) => {
        mediaListeners.push(cb);
      },
      removeEventListener: (_type: string, cb: () => void) => {
        mediaListeners = mediaListeners.filter((l) => l !== cb);
      },
      dispatchEvent: () => false
    })) as unknown as typeof window.matchMedia;
  }

  function fireMediaChange(): void {
    for (const cb of mediaListeners) cb();
  }

  function disableStorage(): void {
    const throwing = (): never => {
      throw new Error("storage disabled");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(throwing);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(throwing);
  }

  // read-only / quota 部分障害: getItem は旧値を返すが setItem は throw する (F-G5)。
  function readOnlyStorageWith(value: string): void {
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(value);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation((): never => {
      throw new Error("read-only storage");
    });
  }

  afterEach(() => {
    vi.restoreAllMocks();
    // jsdom default (matchMedia 未定義) に戻す。
    // @ts-expect-error cleanup: matchMedia を未定義へ戻す
    delete window.matchMedia;
    mediaListeners = [];
    document.documentElement.classList.remove("dark");
  });

  it("設定で選んだ dark が、後から mount する nav toggle でも維持される (system に巻き戻らない)", () => {
    disableStorage();
    const { unmount } = render(<AppearanceSettings />);
    // storage 書込は失敗するが in-session 選択 dark は保持される。
    fireEvent.click(screen.getByRole("radio", { name: /ダーク/ }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // 設定画面を離れ、後で nav toggle が mount する状況を再現。
    unmount();
    render(<ThemeToggle />);

    // storage は読めず system に倒れるが、in-session の dark 選択が引き継がれる。
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(screen.getByRole("button").getAttribute("aria-label")).toContain("現在: ダーク");
  });

  it("dark 選択中は OS preference 変更 (matchMedia change) で system に戻らない", () => {
    disableStorage();
    installMatchMedia(false); // OS は light
    render(
      <>
        <ThemeToggle />
        <AppearanceSettings />
      </>
    );
    fireEvent.click(screen.getByRole("radio", { name: /ダーク/ }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // OS preference の change が来ても、明示選択 dark は維持される。
    fireMediaChange();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("system のときは OS preference 変更が反映される (storage 不可でも追従)", () => {
    disableStorage();
    installMatchMedia(true); // OS は dark
    render(<ThemeToggle />);
    // 初期は明示選択なし → system。OS dark なので .dark。
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // OS change を発火しても system のままなので OS dark に追従する。
    document.documentElement.classList.remove("dark");
    fireMediaChange();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("read-only storage (getItem は旧値 dark / setItem 失敗) で選択 light が stale dark に再上書きされない (F-G5)", () => {
    // storage には dark が残っているが setItem は失敗する (quota / read-only)。
    readOnlyStorageWith("dark");
    installMatchMedia(false); // OS は light
    const { unmount } = render(<AppearanceSettings />);
    // 初期は保存値 dark。
    expect(screen.getByRole("radio", { name: /ダーク/ })).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // light を明示選択 (setItem 失敗 → dirty な in-session light)。
    fireEvent.click(screen.getByRole("radio", { name: /ライト/ }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    // 別 consumer が後から mount しても、stale な保存値 dark ではなく in-session light が優先される。
    unmount();
    render(<ThemeToggle />);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(screen.getByRole("button").getAttribute("aria-label")).toContain("現在: ライト");

    // dirty 中は OS preference 変更でも light を維持する (system に戻らない)。
    fireMediaChange();
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
