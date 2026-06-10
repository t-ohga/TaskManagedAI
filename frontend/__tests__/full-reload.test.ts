// C-5 第 2 round / Codex adversarial F-1/R2/R3 の回帰 test:
// 副次 mutation (コメント / タグ / ステータス / 中止) が、同一ページのチケット編集フォームの
// 未保存入力を警告なしに破棄しないこと (data-dirty 検知 + pre-commit confirm gate)。
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmDiscardUnsavedTicketEdit,
  fullReload,
  hasUnsavedTicketEdit
} from "@/lib/full-reload";

function mountEditForm(html: string): void {
  document.body.innerHTML = `<form data-testid="edit-ticket-form">${html}</form>`;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("hasUnsavedTicketEdit (C-5 R3: data-dirty 一本化)", () => {
  it("編集フォームが無いページでは false", () => {
    expect(hasUnsavedTicketEdit()).toBe(false);
  });

  it("data-dirty 未設定 (未編集) は false", () => {
    mountEditForm('<input name="title" value="t" />');
    expect(hasUnsavedTicketEdit()).toBe(false);
  });

  it("form の data-dirty=true で dirty と判定する (controlled 含む全 field を input bubble で捕捉)", () => {
    mountEditForm('<input name="title" value="t" />');
    const form = document.querySelector("form");
    if (form) form.dataset.dirty = "true";
    expect(hasUnsavedTicketEdit()).toBe(true);
  });
});

describe("confirmDiscardUnsavedTicketEdit (C-5 R2 pre-commit gate)", () => {
  it("dirty なし → confirm を出さず true (mutation 続行)", () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    expect(confirmDiscardUnsavedTicketEdit()).toBe(true);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("dirty + キャンセル → false (mutation 自体を実行させない)", () => {
    mountEditForm('<input name="title" value="t" />');
    const form = document.querySelector("form");
    if (form) form.dataset.dirty = "true";
    vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(confirmDiscardUnsavedTicketEdit()).toBe(false);
  });

  it("dirty + 承認 → true (ユーザー選択で破棄を許可)", () => {
    mountEditForm('<input name="title" value="t" />');
    const form = document.querySelector("form");
    if (form) form.dataset.dirty = "true";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    expect(confirmDiscardUnsavedTicketEdit()).toBe(true);
  });
});

describe("fullReload (R2: 確認は pre-commit gate に移管済)", () => {
  it("無条件で reload する (gate 通過後にのみ呼ばれる契約)", () => {
    const reload = vi.fn();
    fullReload(reload);
    expect(reload).toHaveBeenCalledOnce();
  });
});
