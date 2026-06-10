// C-5 第 2 round / Codex adversarial F-1 の回帰 test:
// 副次 mutation (コメント / タグ / ステータス) 成功後の full reload が、同一ページの
// チケット編集フォームの未保存入力を警告なしに破棄しないこと (dirty 検知 + confirm guard)。
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

describe("hasUnsavedTicketEdit (C-5 F-1)", () => {
  it("編集フォームが無いページでは false", () => {
    expect(hasUnsavedTicketEdit()).toBe(false);
  });

  it("未変更 (value == defaultValue) は false", () => {
    mountEditForm('<input name="title" value="t" /><textarea name="description">d</textarea>');
    expect(hasUnsavedTicketEdit()).toBe(false);
  });

  it("text 入力の変更を dirty と判定する", () => {
    mountEditForm('<input name="title" value="t" />');
    const input = document.querySelector("input");
    if (input) input.value = "edited";
    expect(hasUnsavedTicketEdit()).toBe(true);
  });

  it("select の変更を dirty と判定する", () => {
    mountEditForm(
      '<select name="status"><option value="open" selected>open</option><option value="closed">closed</option></select>'
    );
    const select = document.querySelector("select");
    if (select) select.selectedIndex = 1;
    expect(hasUnsavedTicketEdit()).toBe(true);
  });

  it("hidden input の差分は dirty 扱いしない (React が管理する内部 field)", () => {
    mountEditForm('<input type="hidden" name="ticket_id" value="x" />');
    const hidden = document.querySelector("input");
    if (hidden) hidden.value = "y";
    expect(hasUnsavedTicketEdit()).toBe(false);
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
    const input = document.querySelector("input");
    if (input) input.value = "edited";
    vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(confirmDiscardUnsavedTicketEdit()).toBe(false);
  });

  it("dirty + 承認 → true (ユーザー選択で破棄を許可)", () => {
    mountEditForm('<input name="title" value="t" />');
    const input = document.querySelector("input");
    if (input) input.value = "edited";
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
