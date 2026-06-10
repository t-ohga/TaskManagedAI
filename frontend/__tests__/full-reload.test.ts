// C-5 第 2 round / Codex adversarial F-1/R2/R3 の回帰 test:
// 副次 mutation (コメント / タグ / ステータス / 中止) が、同一ページのチケット編集フォームの
// 未保存入力を警告なしに破棄しないこと (data-dirty 検知 + pre-commit confirm gate)。
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmDiscardUnsavedDrafts,
  fullReload,
  hasUnsavedDraft
} from "@/lib/full-reload";

function mountGuard(dirty: boolean, html = ""): HTMLElement {
  document.body.innerHTML = `<form data-testid="edit-ticket-form" data-unsaved-guard${dirty ? ' data-dirty="true"' : ""}>${html}</form>`;
  const el = document.querySelector("form");
  if (!el) throw new Error("guard mount failed");
  return el;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("hasUnsavedDraft (C-5 R3: data-dirty 一本化)", () => {
  it("編集フォームが無いページでは false", () => {
    expect(hasUnsavedDraft()).toBe(false);
  });

  it("data-dirty 未設定 (未編集) は false", () => {
    mountGuard(false);
    expect(hasUnsavedDraft()).toBe(false);
  });

  it("guard 領域の data-dirty=true で dirty と判定する", () => {
    mountGuard(true);
    expect(hasUnsavedDraft()).toBe(true);
  });

  it("except に渡した領域 (自分の draft) は無視する (R4: 自操作で confirm を出さない)", () => {
    const el = mountGuard(true);
    expect(hasUnsavedDraft(el)).toBe(false);
  });

  it("except 外の別 guard 領域の draft は検知する (R4: コメント draft 等の保護)", () => {
    document.body.innerHTML =
      '<form id="a" data-unsaved-guard data-dirty="true"></form>' +
      '<div id="b" data-unsaved-guard></div>';
    const b = document.querySelector("#b");
    expect(hasUnsavedDraft(b)).toBe(true);
  });
});

describe("confirmDiscardUnsavedDrafts (C-5 R2 pre-commit gate)", () => {
  it("dirty なし → confirm を出さず true (mutation 続行)", () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    expect(confirmDiscardUnsavedDrafts()).toBe(true);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("dirty + キャンセル → false (mutation 自体を実行させない)", () => {
    mountGuard(true);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(confirmDiscardUnsavedDrafts()).toBe(false);
  });

  it("dirty + 承認 → true (ユーザー選択で破棄を許可)", () => {
    mountGuard(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    expect(confirmDiscardUnsavedDrafts()).toBe(true);
  });
});

describe("fullReload (R2: 確認は pre-commit gate に移管済)", () => {
  it("無条件で reload する (gate 通過後にのみ呼ばれる契約)", () => {
    const reload = vi.fn();
    fullReload(reload);
    expect(reload).toHaveBeenCalledOnce();
  });
});
