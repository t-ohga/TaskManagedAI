import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TicketTagManager } from "@/components/ticket-tag-manager";
import type { TagRead } from "@/lib/domain/tag";

// Server Action と router を mock し、各操作が正しい action / FormData を呼ぶことを検証する。
// C-5 第 2 round: hook は router.refresh ではなく full reload (確実性実測済) を行う。
// C-5 第 2 round: hook は full reload (lib/full-reload seam) を行う。jsdom の location を
// 再定義せず、seam module を mock して検証する (Codex adversarial F-3)。
const reload = vi.fn(() => true);
const discardConfirm = vi.fn(() => true);
vi.mock("@/lib/full-reload", async (importOriginal) => {
  // R6: except 粒度 (create/rename guard) を実 hasUnsavedDraft で検証するため、
  // gate の判定は実装を使い、confirm と reload だけ差し替える。
  const actual = (await importOriginal()) as {
    hasUnsavedDraft: (except?: Element | null) => boolean;
  } & Record<string, unknown>;
  return {
    ...actual,
    fullReload: () => reload(),
    confirmDiscardUnsavedDrafts: (except?: Element | null) => {
      if (!actual.hasUnsavedDraft(except)) return true;
      return discardConfirm();
    }
  };
});

const actionCalls: { name: string; entries: Record<string, string> }[] = [];
function record(name: string) {
  return async (_state: unknown, fd: FormData) => {
    const entries: Record<string, string> = {};
    for (const [k, v] of fd.entries()) entries[k] = String(v);
    actionCalls.push({ name, entries });
    return { kind: "ok" as const };
  };
}
vi.mock("@/app/(admin)/tickets/[id]/tag-actions", () => ({
  attachTagAction: (s: unknown, fd: FormData) => record("attach")(s, fd),
  detachTagAction: (s: unknown, fd: FormData) => record("detach")(s, fd),
  createTagAndAttachAction: (s: unknown, fd: FormData) => record("create")(s, fd),
  renameTagAction: (s: unknown, fd: FormData) => record("rename")(s, fd),
  deleteTagAction: (s: unknown, fd: FormData) => record("delete")(s, fd)
}));

const TICKET_ID = "00000000-0000-4000-8000-000000000abc";
const TAG_A: TagRead = { id: "00000000-0000-4000-8000-00000000a001", name: "bug", color: "red" };
const TAG_B: TagRead = { id: "00000000-0000-4000-8000-00000000b002", name: "docs", color: "blue" };

beforeEach(() => {
  actionCalls.length = 0;
  reload.mockClear();
});

describe("TicketTagManager", () => {
  it("detaches an attached tag via detachTagAction with ticket_id + tag_id", async () => {
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[TAG_A]} allTags={[TAG_A, TAG_B]} />);
    fireEvent.click(screen.getByLabelText("タグ「bug」をこのチケットから外す"));
    await waitFor(() => expect(actionCalls).toHaveLength(1));
    expect(actionCalls[0]).toEqual({
      name: "detach",
      entries: { ticket_id: TICKET_ID, tag_id: TAG_A.id }
    });
    // C-5 workaround: useDeferredRouterRefresh の effect 経由で reload が非同期到達する。
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it("attaches an available (unassigned) tag via attachTagAction", async () => {
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[TAG_A]} allTags={[TAG_A, TAG_B]} />);
    fireEvent.click(screen.getByLabelText("タグ「docs」をこのチケットに付与する"));
    await waitFor(() => expect(actionCalls).toHaveLength(1));
    expect(actionCalls[0]).toEqual({
      name: "attach",
      entries: { ticket_id: TICKET_ID, tag_id: TAG_B.id }
    });
  });

  it("creates a new tag with name + color and attaches it", async () => {
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[]} allTags={[]} />);
    fireEvent.click(screen.getByText("+ 新しいタグを作成"));
    fireEvent.change(screen.getByLabelText("新しいタグ名"), { target: { value: "urgent" } });
    fireEvent.click(screen.getByLabelText("green"));
    fireEvent.click(screen.getByText("作成して付与"));
    await waitFor(() => expect(actionCalls).toHaveLength(1));
    expect(actionCalls[0]).toEqual({
      name: "create",
      entries: { ticket_id: TICKET_ID, name: "urgent", color: "green" }
    });
  });

  it("does not submit create when name is empty", async () => {
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[]} allTags={[]} />);
    fireEvent.click(screen.getByText("+ 新しいタグを作成"));
    fireEvent.click(screen.getByText("作成して付与"));
    expect(actionCalls).toHaveLength(0);
    expect(screen.getByText("タグ名を入力してください。")).toBeInTheDocument();
  });
});

// R6 (Codex adversarial HIGH) 回帰: tag panel 内の draft 粒度。
describe("TicketTagManager guard granularity (R6)", () => {
  it("新規タグ draft 入力中に attach すると確認され、拒否なら action も reload も実行しない", async () => {
    discardConfirm.mockReturnValue(false);
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[TAG_A]} allTags={[TAG_A, TAG_B]} />);
    // 新規作成パネルを開いて draft を入力
    fireEvent.click(screen.getByRole("button", { name: /新しいタグ|新規/ }));
    fireEvent.change(screen.getByLabelText("新しいタグ名"), { target: { value: "draft-tag" } });
    // 別タグの attach (draft を consume しない操作)
    fireEvent.click(screen.getByLabelText("タグ「docs」をこのチケットに付与する"));

    await new Promise((r) => setTimeout(r, 50));
    expect(discardConfirm).toHaveBeenCalled();
    expect(actionCalls).toHaveLength(0);
    expect(reload).not.toHaveBeenCalled();
  });

  it("新規タグ draft の作成確定 (consume) は確認なしで実行される (except=create 領域)", async () => {
    render(<TicketTagManager ticketId={TICKET_ID} currentTags={[TAG_A]} allTags={[TAG_A, TAG_B]} />);
    fireEvent.click(screen.getByRole("button", { name: /新しいタグ|新規/ }));
    fireEvent.change(screen.getByLabelText("新しいタグ名"), { target: { value: "draft-tag" } });
    fireEvent.click(screen.getByRole("button", { name: "作成して付与" }));

    await waitFor(() => expect(actionCalls).toHaveLength(1));
    expect(actionCalls[0]?.name).toBe("create");
    expect(discardConfirm).not.toHaveBeenCalled();
  });
});

