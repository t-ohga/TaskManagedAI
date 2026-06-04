"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type Theme,
  THEME_STORAGE_KEY,
  applyTheme,
  readStoredTheme
} from "@/lib/theme";

// M-2 (ADR-00047): テーマ state hook (client)。nav の cycling toggle と設定ページの 3 択 selector が
// 同じ state を共有する (plan-review R1 F-002: 既存 theme-toggle と統一)。同一 tab 同期は custom event、
// 別 tab 同期は storage event (R1 F-002 / R2: event→setState のみで再 dispatch しないため無限ループなし)。

const THEME_CHANGE_EVENT = "tm:themechange";

export function useTheme(): { theme: Theme; setTheme: (next: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>("system");

  useEffect(() => {
    // localStorage は SSR で読めないため hydration 後に反映する (initializer で読むと mismatch)。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThemeState(readStoredTheme());

    // Codex adversarial F-D1: 別 tab で theme が変わったら React state だけでなく **DOM の `.dark` class
    // にも applyTheme を再適用** する。`.dark` はグローバル副作用で React 描画属性ではないため、state
    // 更新だけだと「controls は新値表示・配色は旧のまま」と乖離する。applyTheme は idempotent なので
    // 同 tab custom event 経路 (setTheme で適用済) で再呼びしても害はない。
    const syncFromStorage = (): void => {
      const next = readStoredTheme();
      applyTheme(next);
      setThemeState(next);
    };
    const onStorage = (event: StorageEvent): void => {
      // この key の変更、または別 tab の localStorage.clear() (key === null) → system へ再同期。
      if (event.key === THEME_STORAGE_KEY || event.key === null) syncFromStorage();
    };
    const onCustom = (): void => syncFromStorage();
    window.addEventListener("storage", onStorage);
    window.addEventListener(THEME_CHANGE_EVENT, onCustom);

    // theme="system" のとき OS のダーク設定変更に追従する。matchMedia 非対応環境 (一部 test 環境等)
    // でも壊れないよう guard する (applyTheme/systemPrefersDark と同じ防御)。
    const mq =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;
    const onMediaChange = (): void => {
      if (readStoredTheme() === "system") applyTheme("system");
    };
    mq?.addEventListener("change", onMediaChange);

    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(THEME_CHANGE_EVENT, onCustom);
      mq?.removeEventListener("change", onMediaChange);
    };
  }, []);

  const setTheme = useCallback((next: Theme) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // localStorage 不可 (private mode 等) でも適用は続ける。
    }
    applyTheme(next);
    setThemeState(next);
    // 同一 tab の他の useTheme インスタンス (nav toggle ↔ 設定 selector) に通知する
    // (storage event は別 tab のみ発火するため)。再 dispatch しないので無限ループしない。
    window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
  }, []);

  return { theme, setTheme };
}
