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

  it("承認 = 即破棄: dirty クリア + form.reset で server 値へ戻る (R9)", () => {
    // R9 シナリオ封鎖の核: 承認済み draft が物理的に消えるため、reload 直前再確認 (R7) の
    // 対象にならず、拒否で残った form も defaultValue (server 値) = R8 drop で巻き戻し不能。
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "stale-draft";
    vi.spyOn(window, "confirm").mockReturnValue(true);

    expect(confirmDiscardUnsavedDrafts()).toBe(true);
    expect((form as HTMLElement).dataset.dirty).toBeUndefined();
    expect(hasUnsavedDraft()).toBe(false);
    expect(input?.value).toBe("server-value");
  });

  it("承認時も except 領域の draft は破棄しない", () => {
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "my-own-draft";
    // 別領域の dirty guard を追加して confirm を発生させる
    const other = document.createElement("div");
    other.setAttribute("data-unsaved-guard", "");
    other.dataset.dirty = "true";
    document.body.appendChild(other);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    expect(confirmDiscardUnsavedDrafts(form)).toBe(true);
    // except (自領域) の draft は保持、他領域は破棄。
    expect(input?.value).toBe("my-own-draft");
    expect((form as HTMLElement).dataset.dirty).toBe("true");
    expect(other.dataset.dirty).toBeUndefined();
  });
});

describe("fullReload (R2: 確認は pre-commit gate に移管済)", () => {
  it("無条件で reload する (gate 通過後にのみ呼ばれる契約)", () => {
    const reload = vi.fn();
    fullReload(reload);
    expect(reload).toHaveBeenCalledOnce();
  });
});
