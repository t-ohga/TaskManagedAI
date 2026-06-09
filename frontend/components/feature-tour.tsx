"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  TOUR_STEPS,
  markTourCompleted,
  progressLabel,
  readTourCompleted
} from "@/lib/feature-tour";

// 同一 session 内で一度表示したら自動再表示しない (storage がブロックされ readTourCompleted が常に
// false でも、navigation のたびに開かないようにする module-level guard。M-2 の session source-of-truth 同型)。
let sessionAutoShown = false;

/** test 用: module-level session guard を reset する。 */
export function __resetFeatureTourSessionForTest(): void {
  sessionAutoShown = false;
}

export const OPEN_FEATURE_TOUR_EVENT = "taskmanagedai:open-feature-tour";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusableWithin(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

export function FeatureTour() {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  // open 前に focus していた要素 (close 時に focus を戻す、a11y)。
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // 初回訪問の自動表示 (client only、未完了 かつ 同一 session 未表示のときだけ)。
  // localStorage は SSR で読めないため hydration 後に判定する (M-2 use-theme.ts と同型の
  // localStorage-sync-in-effect、初期 index=0)。
  useEffect(() => {
    if (sessionAutoShown) return;
    if (readTourCompleted()) return;
    sessionAutoShown = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(true);
  }, []);

  // ナビの「ガイド」ボタンからの手動再表示。
  useEffect(() => {
    function handleOpen(): void {
      sessionAutoShown = true;
      setIndex(0);
      setOpen(true);
    }
    window.addEventListener(OPEN_FEATURE_TOUR_EVENT, handleOpen);
    return () => window.removeEventListener(OPEN_FEATURE_TOUR_EVENT, handleOpen);
  }, []);

  const dismiss = useCallback(() => {
    markTourCompleted();
    setOpen(false);
  }, []);

  // Escape で閉じる + focus trap (Tab/Shift+Tab を dialog 内で循環) + close 時 focus 復元。
  // aria-modal="true" を宣言する以上、依存ゼロで focus が背後の admin UI へ漏れないようにする
  // (Codex adversarial R1 MEDIUM)。
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();

    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        event.stopPropagation();
        dismiss();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = focusableWithin(dialogRef.current);
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (!first || !last) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || active === dialogRef.current) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      // close 時に open 前の focus へ戻す (要素が外れていれば no-op)。
      previousFocusRef.current?.focus?.();
    };
  }, [open, dismiss]);

  if (!open) return null;

  const step = TOUR_STEPS[index];
  if (!step) return null;
  const isFirst = index === 0;
  const isLast = index === TOUR_STEPS.length - 1;

  return (
    // backdrop。dismiss は ✕ / Escape / スキップ / 完了 で行う (backdrop クリックは a11y 上の
    // static-element-interaction を避けるため設けない)。
    <div className="no-print fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="feature-tour-title"
        tabIndex={-1}
        className="w-full max-w-md rounded-xl border border-line bg-panel p-6 shadow-xl outline-none"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="text-2xl">
              {step.icon}
            </span>
            <h2 id="feature-tour-title" className="text-lg font-semibold text-ink">
              {step.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={dismiss}
            aria-label="ツアーを閉じる"
            className="rounded-md p-1 text-muted-foreground hover:bg-canvas hover:text-ink"
          >
            ✕
          </button>
        </div>

        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{step.description}</p>

        <Link
          href={step.href}
          onClick={() => setOpen(false)}
          className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
        >
          この画面を開く →
        </Link>

        <div className="mt-6 flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground" aria-live="polite">
            {progressLabel(index)}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={dismiss}
              className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:text-ink"
            >
              スキップ
            </button>
            <button
              type="button"
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
              disabled={isFirst}
              className="rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:bg-canvas disabled:opacity-40"
            >
              前へ
            </button>
            {isLast ? (
              <button
                type="button"
                onClick={dismiss}
                className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90"
              >
                完了
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setIndex((i) => Math.min(TOUR_STEPS.length - 1, i + 1))}
                className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90"
              >
                次へ
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
