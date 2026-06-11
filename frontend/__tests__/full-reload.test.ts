// C-5 第 2 round / Codex adversarial F-1/R2/R3 の回帰 test:
// 副次 mutation (コメント / タグ / ステータス / 中止) が、同一ページのチケット編集フォームの
// 未保存入力を警告なしに破棄しないこと (data-dirty 検知 + pre-commit confirm gate)。
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmDiscardUnsavedDrafts,
  fullReload,
  hasUnsavedDraft,
  prepareDiscardOnCommit
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

describe("confirmDiscardUnsavedDrafts (確認のみ: R7 reload 直前再確認 / R11 で破棄分離)", () => {
  it("dirty なし → confirm を出さず true (mutation 続行)", () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    expect(confirmDiscardUnsavedDrafts()).toBe(true);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("dirty + キャンセル → false (reload しない)", () => {
    mountGuard(true);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(confirmDiscardUnsavedDrafts()).toBe(false);
  });

  it("dirty + 承認 → true。**破棄はしない** (R11: 確認のみ、破棄は commit 経由)", () => {
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "stale-draft";
    vi.spyOn(window, "confirm").mockReturnValue(true);

    expect(confirmDiscardUnsavedDrafts()).toBe(true);
    // 確認のみ。dirty / 入力値は保持される (破棄は prepareDiscardOnCommit().commit() の責務)。
    expect((form as HTMLElement).dataset.dirty).toBe("true");
    expect(input?.value).toBe("stale-draft");
  });
});

describe("prepareDiscardOnCommit (R11: 破棄は成功時 commit のみ、失敗時は無傷)", () => {
  it("dirty なし → confirm を出さず approved=true / commit は no-op", () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    const { approved, commit } = prepareDiscardOnCommit();
    expect(approved).toBe(true);
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(() => commit()).not.toThrow();
  });

  it("dirty + キャンセル → approved=false / commit は no-op (draft 無傷)", () => {
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "stale-draft";
    vi.spyOn(window, "confirm").mockReturnValue(false);

    const { approved, commit } = prepareDiscardOnCommit();
    expect(approved).toBe(false);
    commit();
    // 拒否 → mutation 中止。draft は完全に無傷。
    expect((form as HTMLElement).dataset.dirty).toBe("true");
    expect(input?.value).toBe("stale-draft");
  });

  it("承認 + **commit 未呼び出し (mutation 失敗)** → draft 無傷 (R11 の核)", () => {
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "stale-draft";
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const { approved } = prepareDiscardOnCommit();
    expect(approved).toBe(true);
    // mutation 失敗 → commit() を呼ばない。承認済みでも draft は消えない。
    expect((form as HTMLElement).dataset.dirty).toBe("true");
    expect(hasUnsavedDraft()).toBe(true);
    expect(input?.value).toBe("stale-draft");
  });

  it("承認 + **commit 呼び出し (mutation 成功)** → dirty クリア + form.reset で server 値へ", () => {
    // 成功時のみ破棄 = R8 の touched-field-only PATCH と整合 (server 値へ戻り巻き戻し不能)。
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "stale-draft";
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const { approved, commit } = prepareDiscardOnCommit();
    expect(approved).toBe(true);
    commit();
    expect((form as HTMLElement).dataset.dirty).toBeUndefined();
    expect(hasUnsavedDraft()).toBe(false);
    expect(input?.value).toBe("server-value");
  });

  it("commit は except 領域の draft を破棄しない (自操作の自分の draft を保持)", () => {
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "my-own-draft";
    const other = document.createElement("div");
    other.setAttribute("data-unsaved-guard", "");
    other.dataset.dirty = "true";
    document.body.appendChild(other);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const { approved, commit } = prepareDiscardOnCommit(form);
    expect(approved).toBe(true);
    commit();
    // except (自領域) の draft は保持、他領域のみ破棄。
    expect(input?.value).toBe("my-own-draft");
    expect((form as HTMLElement).dataset.dirty).toBe("true");
    expect(other.dataset.dirty).toBeUndefined();
  });

  it("commit は捕捉時点の dirty guard のみ破棄 (commit 前に新規 dirty 化した guard N は保持 = R7 へ)", () => {
    mountGuard(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { commit } = prepareDiscardOnCommit();

    // mutation 中に新規 draft N が作られた状況を再現 (捕捉後に dirty 化)
    const fresh = document.createElement("div");
    fresh.setAttribute("data-unsaved-guard", "");
    fresh.dataset.dirty = "true";
    document.body.appendChild(fresh);

    commit();
    // 捕捉済みの旧 guard は破棄されるが、捕捉後に dirty 化した N は保持 (reload 直前 R7 再確認の対象)。
    expect(fresh.dataset.dirty).toBe("true");
  });

  it("R12: 承認後に同じ捕捉 guard を編集したら commit は破棄せず dirty を残す (R7 へ委譲)", () => {
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "approved-content";
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const { approved, commit } = prepareDiscardOnCommit();
    expect(approved).toBe(true);

    // 承認後〜commit の間にユーザーが同じ draft を編集し続ける (cross-component の slow mutation 中)
    if (input) input.value = "edited-after-approval";

    commit();
    // signature 不一致 → 破棄されず、編集内容と dirty が保持される (無確認破棄の封鎖)
    expect((form as HTMLElement).dataset.dirty).toBe("true");
    expect(input?.value).toBe("edited-after-approval");
    expect(hasUnsavedDraft()).toBe(true);
  });

  it("R12: 承認後に編集せず commit すれば従来どおり破棄される (signature 一致)", () => {
    const form = mountGuard(true, '<input name="title" value="server-value" />');
    const input = document.querySelector("input");
    if (input) input.value = "approved-content";
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const { commit } = prepareDiscardOnCommit();
    commit();
    expect((form as HTMLElement).dataset.dirty).toBeUndefined();
    expect(input?.value).toBe("server-value");
  });
});

describe("fullReload (R2: 確認は pre-commit gate に移管済)", () => {
  it("無条件で reload する (gate 通過後にのみ呼ばれる契約)", () => {
    const reload = vi.fn();
    fullReload(reload);
    expect(reload).toHaveBeenCalledOnce();
  });
});
