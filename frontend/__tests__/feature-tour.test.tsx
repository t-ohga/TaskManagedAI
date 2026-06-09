import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  FeatureTour,
  OPEN_FEATURE_TOUR_EVENT,
  __resetFeatureTourSessionForTest
} from "@/components/feature-tour";
import { TOUR_STEPS, TOUR_STORAGE_KEY, TOUR_VERSION } from "@/lib/feature-tour";

function stepTitle(index: number): string {
  const step = TOUR_STEPS[index];
  if (!step) throw new Error(`no tour step at ${index}`);
  return step.title;
}

beforeEach(() => {
  localStorage.clear();
  __resetFeatureTourSessionForTest();
});

afterEach(() => {
  localStorage.clear();
});

describe("FeatureTour", () => {
  it("初回訪問で自動表示し最初のステップを示す", () => {
    render(<FeatureTour />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: stepTitle(0) })).toBeVisible();
    expect(screen.getByText(`1 / ${TOUR_STEPS.length}`)).toBeInTheDocument();
  });

  it("次へ/前へでステップを移動する", () => {
    render(<FeatureTour />);
    fireEvent.click(screen.getByRole("button", { name: "次へ" }));
    expect(screen.getByRole("heading", { name: stepTitle(1) })).toBeVisible();
    expect(screen.getByText(`2 / ${TOUR_STEPS.length}`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "前へ" }));
    expect(screen.getByRole("heading", { name: stepTitle(0) })).toBeVisible();
  });

  it("最初のステップでは前へが無効", () => {
    render(<FeatureTour />);
    expect(screen.getByRole("button", { name: "前へ" })).toBeDisabled();
  });

  it("スキップで完了をマークし閉じる", () => {
    render(<FeatureTour />);
    fireEvent.click(screen.getByRole("button", { name: "スキップ" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(TOUR_STORAGE_KEY)).toBe(TOUR_VERSION);
  });

  it("Escape で閉じて完了をマークする", () => {
    render(<FeatureTour />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(TOUR_STORAGE_KEY)).toBe(TOUR_VERSION);
  });

  it("完了済みなら自動表示しない", () => {
    localStorage.setItem(TOUR_STORAGE_KEY, TOUR_VERSION);
    render(<FeatureTour />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("完了済みでも open イベントで手動再表示できる", () => {
    localStorage.setItem(TOUR_STORAGE_KEY, TOUR_VERSION);
    render(<FeatureTour />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent(window, new Event(OPEN_FEATURE_TOUR_EVENT));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: stepTitle(0) })).toBeVisible();
  });

  it("focus trap: 最後の要素から Tab で先頭へ循環する (背後へ漏れない)", () => {
    render(<FeatureTour />);
    // component と同じ DOM 順の focusable 集合 (前へ disabled は除外)。
    const dialog = screen.getByRole("dialog");
    const focusables = Array.from(
      dialog.querySelectorAll<HTMLElement>("a[href], button:not([disabled])")
    );
    const first = focusables[0] as HTMLElement;
    const last = focusables[focusables.length - 1] as HTMLElement;
    last.focus();
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);
  });

  it("focus trap: 先頭から Shift+Tab で末尾へ循環する", () => {
    render(<FeatureTour />);
    const dialog = screen.getByRole("dialog");
    const focusables = Array.from(
      dialog.querySelectorAll<HTMLElement>("a[href], button:not([disabled])")
    );
    const first = focusables[0] as HTMLElement;
    const last = focusables[focusables.length - 1] as HTMLElement;
    first.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("close 時に open 前の focus を復元する", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);
    render(<FeatureTour />);
    // 自動表示で dialog に focus が移る
    fireEvent.click(screen.getByRole("button", { name: "スキップ" }));
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it("最終ステップで完了ボタンを表示しクリックで閉じる", () => {
    render(<FeatureTour />);
    for (let i = 0; i < TOUR_STEPS.length - 1; i += 1) {
      fireEvent.click(screen.getByRole("button", { name: "次へ" }));
    }
    const done = screen.getByRole("button", { name: "完了" });
    expect(done).toBeInTheDocument();
    fireEvent.click(done);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(TOUR_STORAGE_KEY)).toBe(TOUR_VERSION);
  });
});
