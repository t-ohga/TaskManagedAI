// R10 (Codex adversarial HIGH) 回帰 test:
// discardDrafts() の DOM 操作 (dirty 削除 + form.reset()) だけでは React state を正本とする
// draft が次 render で復活する (controlled value / state 由来 data-dirty)。本 test は **実 component**
// (CommentForm / TicketTagManager / EditTicketForm) で、破棄承認後に再 render しても stale 値と
// data-dirty が戻らないことを固定する (DRAFT_DISCARD_EVENT → component state 破棄の配線検証)。
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CommentForm } from "@/components/comment-form";
import { TicketTagManager } from "@/components/ticket-tag-manager";
import { EditTicketForm } from "../app/(admin)/tickets/[id]/_components/edit-ticket-form";
import { prepareDiscardOnCommit } from "@/lib/full-reload";
import type { TagRead } from "@/lib/domain/tag";

const routerMocks = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => routerMocks
}));

vi.mock("@/app/(admin)/tickets/[id]/tag-actions", () => ({
  attachTagAction: async () => ({ kind: "ok" as const }),
  detachTagAction: async () => ({ kind: "ok" as const }),
  createTagAndAttachAction: async () => ({ kind: "ok" as const }),
  renameTagAction: async () => ({ kind: "ok" as const }),
  deleteTagAction: async () => ({ kind: "ok" as const })
}));
vi.mock("../app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async () => ({ kind: "ok" as const, ticket_id: "x", ticket: null })
}));
vi.mock("@/app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async () => ({ kind: "ok" as const, ticket_id: "x", ticket: null })
}));

const TICKET_ID = "00000000-0000-4000-8000-000000000abc";
const TAG_A: TagRead = { id: "00000000-0000-4000-8000-00000000a001", name: "bug", color: "red" };

beforeEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

// 他領域 mutation が「成功」した経路を再現する: pre-commit で確認・捕捉 (prepareDiscardOnCommit)
// → 成功時に commit() で破棄。except なし = 画面上の全 draft が捕捉・破棄対象。
function approveAndCommitDiscard(): void {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  act(() => {
    const { approved, commit } = prepareDiscardOnCommit();
    expect(approved).toBe(true);
    commit();
  });
}

// 他領域 mutation が「失敗」した経路: 確認・捕捉までは行うが commit() を呼ばない (R11)。
function approveButDoNotCommit(): void {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  act(() => {
    const { approved } = prepareDiscardOnCommit();
    expect(approved).toBe(true);
    // commit() を呼ばない = mutation 失敗。draft は無傷であるべき。
  });
}

describe("R10: 承認済み discard が React state ごと draft を破棄する", () => {
  it("CommentForm: 破棄承認後に body state が消え、再 render で data-dirty が復活しない", () => {
    render(<CommentForm ticketId={TICKET_ID} onSubmit={async () => ({ kind: "ok" as const })} />);
    const textarea = screen.getByLabelText("コメント本文") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "下書きコメント" } });

    const form = textarea.closest("form") as HTMLFormElement;
    expect(form.dataset.dirty).toBe("true");

    approveAndCommitDiscard();

    // state (body) が破棄され、controlled textarea も空、state 由来の dirty も再付与されない
    expect(textarea.value).toBe("");
    expect(form.dataset.dirty).toBeUndefined();
    // 再 render を誘発しても stale 値が戻らない (state が正本ごと消えている)
    fireEvent.blur(textarea);
    expect(textarea.value).toBe("");
    expect(form.dataset.dirty).toBeUndefined();
  });

  it("TicketTagManager: 新規タグ draft の破棄承認後に newName state が消える", () => {
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[]} allTags={[TAG_A]} />);
    fireEvent.click(screen.getByText("+ 新しいタグを作成"));
    const nameInput = screen.getByLabelText("新しいタグ名") as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "draft-tag" } });

    const guard = nameInput.closest("[data-unsaved-guard]") as HTMLElement;
    expect(guard.dataset.dirty).toBe("true");

    approveAndCommitDiscard();

    expect(nameInput.value).toBe("");
    expect(guard.dataset.dirty).toBeUndefined();
  });

  it("TicketTagManager: rename draft の破棄承認後に編集行 (editingId state) が閉じる", () => {
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[]} allTags={[TAG_A]} />);
    // details を開いて rename 編集を開始
    fireEvent.click(screen.getByText("タグを管理 (名前・色の変更 / 削除)"));
    fireEvent.click(screen.getByText("編集"));
    const editInput = screen.getByLabelText("タグ「bug」の新しい名前") as HTMLInputElement;
    expect(editInput).toBeInTheDocument();

    approveAndCommitDiscard();

    // editingId が破棄され、dirty="true" の編集行ごと閉じる
    expect(screen.queryByLabelText("タグ「bug」の新しい名前")).not.toBeInTheDocument();
    expect(document.querySelector('[data-unsaved-guard][data-dirty="true"]')).toBeNull();
  });

  it("EditTicketForm: description (MarkdownEditor 内部 state) が破棄承認で server 値に戻る", () => {
    render(
      <EditTicketForm
        ticket={{
          id: TICKET_ID,
          title: "server title",
          description: "server description",
          due_date: null,
          status: "open",
          priority: null,
          assignee_actor_id: null,
          updated_at: "2026-06-11T00:00:00Z"
        }}
        assignableActors={[]}
        assignableActorsDegraded={false}
        assignableActorsTruncated={false}
      />
    );
    const description = screen.getByLabelText("説明") as HTMLTextAreaElement;
    fireEvent.change(description, { target: { value: "編集中の stale draft" } });

    const form = screen.getByTestId("edit-ticket-form") as HTMLFormElement;
    expect(form.dataset.dirty).toBe("true");

    approveAndCommitDiscard();

    // nonce remount で MarkdownEditor 内部 state ごと server 値へ戻る
    const after = screen.getByLabelText("説明") as HTMLTextAreaElement;
    expect(after.value).toBe("server description");
    const formAfter = screen.getByTestId("edit-ticket-form") as HTMLFormElement;
    expect(formAfter.dataset.dirty).toBeUndefined();
  });
});

describe("R11: mutation 失敗 (commit 未呼び出し) では draft が破棄されない", () => {
  it("CommentForm: 承認後に他領域 mutation が失敗しても body draft が残る", () => {
    render(<CommentForm ticketId={TICKET_ID} onSubmit={async () => ({ kind: "ok" as const })} />);
    const textarea = screen.getByLabelText("コメント本文") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "失われてはいけない下書き" } });
    const form = textarea.closest("form") as HTMLFormElement;
    expect(form.dataset.dirty).toBe("true");

    approveButDoNotCommit();

    // 承認したが mutation 失敗 (commit 未呼び出し) → draft 完全保持
    expect(textarea.value).toBe("失われてはいけない下書き");
    expect(form.dataset.dirty).toBe("true");
  });

  it("EditTicketForm: 承認後に他領域 mutation が失敗しても description draft が残る", () => {
    render(
      <EditTicketForm
        ticket={{
          id: TICKET_ID,
          title: "server title",
          description: "server description",
          due_date: null,
          status: "open",
          priority: null,
          assignee_actor_id: null,
          updated_at: "2026-06-11T00:00:00Z"
        }}
        assignableActors={[]}
        assignableActorsDegraded={false}
        assignableActorsTruncated={false}
      />
    );
    const description = screen.getByLabelText("説明") as HTMLTextAreaElement;
    fireEvent.change(description, { target: { value: "編集中の作業 (失敗で消えてはいけない)" } });
    const form = screen.getByTestId("edit-ticket-form") as HTMLFormElement;
    expect(form.dataset.dirty).toBe("true");

    approveButDoNotCommit();

    // remount せず draft 保持 (mutation 失敗で server 値に巻き戻さない)
    const after = screen.getByLabelText("説明") as HTMLTextAreaElement;
    expect(after.value).toBe("編集中の作業 (失敗で消えてはいけない)");
    expect(screen.getByTestId("edit-ticket-form").dataset.dirty).toBe("true");
  });
});
