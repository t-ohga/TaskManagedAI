"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type Theme,
  THEME_STORAGE_KEY,
  applyTheme,
  isTheme,
  readStoredTheme
} from "@/lib/theme";

// M-2 (ADR-00047): テーマ state hook (client)。nav の cycling toggle と設定ページの 3 択 selector が
// 同じ state を共有する (plan-review R1 F-002: 既存 theme-toggle と統一)。同一 tab 同期は custom event、
// 別 tab 同期は storage event (R1 F-002 / R2: event→setState のみで再 dispatch しないため無限ループなし)。

const THEME_CHANGE_EVENT = "tm:themechange";

// Codex App F-G4: 同一セッション内で明示選択されたテーマ (module-level の in-memory store)。
// localStorage が使えない環境 (private mode 等で getItem/setItem が throw) では readStoredTheme() が
// 常に "system" を返すため、nav で選んだ Light/Dark が「後から mount する別 consumer の初期化」や
// 「OS preference 変更 (matchMedia change)」で system に巻き戻り、DOM の `.dark` と controls 表示が
// 乖離していた。in-memory の選択値を source of truth に加えてこれを防ぐ。
// storage が機能していれば storage 値が authoritative なので、storage sync 時に in-memory を揃える。
let sessionTheme: Theme | null = null;

/**
 * 実効テーマ。storage 値を優先しつつ、storage 不可時は in-session の明示選択を source of truth にする。
 * - readStoredTheme() が明示値 ("light"/"dark") を返す → storage 由来 (cross-tab 変更含む) を優先。
 * - "system" を返す (storage が "system" を保持 / storage 不可で fallback) → in-session 選択があれば優先。
 */
function effectiveTheme(): Theme {
  const stored = readStoredTheme();
  if (stored !== "system") return stored;
  return sessionTheme ?? "system";
}

/** test 専用: module-level の in-session 選択を初期化する (test 間の状態リークを防ぐ)。 */
export function __resetSessionThemeForTest(): void {
  sessionTheme = null;
}

export function useTheme(): { theme: Theme; setTheme: (next: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>("system");

  useEffect(() => {
    // localStorage は SSR で読めないため hydration 後に反映する (initializer で読むと mismatch)。
    // state だけでなく DOM の `.dark` も applyTheme で揃える: inline script (first paint) が storage の
    // 一時失敗 / 後からの値変更 / script 未注入 (embed/test) で React state と乖離した `.dark` を残して
    // いても、controls と配色を一致させる (Codex App F-G1)。effectiveTheme は in-session 選択を考慮する
    // ため、storage 不可でも先行 consumer の選択を引き継ぐ (Codex App F-G4)。applyTheme は idempotent。
    const initial = effectiveTheme();
    applyTheme(initial);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThemeState(initial);

    // Codex adversarial F-D1: 別 tab で theme が変わったら React state だけでなく **DOM の `.dark` class
    // にも applyTheme を再適用** する。`.dark` はグローバル副作用で React 描画属性ではないため、state
    // 更新だけだと「controls は新値表示・配色は旧のまま」と乖離する。applyTheme は idempotent なので
    // 同 tab custom event 経路 (setTheme で適用済) で再呼びしても害はない。
    // storage event は storage が機能している証左なので、in-memory (sessionTheme) を storage 値へ揃える。
    const syncFromStorage = (): void => {
      const next = readStoredTheme();
      sessionTheme = next;
      applyTheme(next);
      setThemeState(next);
    };
    const onStorage = (event: StorageEvent): void => {
      // この key の変更、または別 tab の localStorage.clear() (key === null) → storage へ再同期。
      if (event.key === THEME_STORAGE_KEY || event.key === null) syncFromStorage();
    };
    // Codex adversarial F-E1: 同一 tab 通知は **dispatch された値 (event.detail) を使い、storage を再読込
    // しない**。storage 無効 (private mode) で setItem が失敗していると、再読込は古い値/system に倒れて
    // 選択を即上書きしてしまうため (in-session 選択は CustomEvent の detail で伝える)。detail が不正な
    // ときのみ effectiveTheme を読む。受信側でも in-session store (sessionTheme) を更新しておく (F-G4)。
    const onCustom = (event: Event): void => {
      const detail = (event as CustomEvent<unknown>).detail;
      const next = isTheme(detail) ? detail : effectiveTheme();
      sessionTheme = next;
      applyTheme(next);
      setThemeState(next);
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(THEME_CHANGE_EVENT, onCustom);

    // theme="system" のとき OS のダーク設定変更に追従する。matchMedia 非対応環境 (一部 test 環境等)
    // でも壊れないよう guard する (applyTheme/systemPrefersDark と同じ防御)。effectiveTheme を使うことで、
    // storage 不可でも明示選択中 (light/dark) は OS 変更で巻き戻らない (Codex App F-G4)。
    const mq =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;
    const onMediaChange = (): void => {
      if (effectiveTheme() === "system") applyTheme("system");
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
    // in-session source of truth を更新 (storage 不可でも current session の選択を維持、F-G4)。
    sessionTheme = next;
    applyTheme(next);
    setThemeState(next);
    // 同一 tab の他の useTheme インスタンス (nav toggle ↔ 設定 selector) に通知する
    // (storage event は別 tab のみ発火するため)。**選択値を detail に載せ** storage 再読込に依存させない
    // (F-E1: storage 無効でも in-session の選択が保持される)。再 dispatch しないので無限ループしない。
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: next }));
  }, []);

  return { theme, setTheme };
}
