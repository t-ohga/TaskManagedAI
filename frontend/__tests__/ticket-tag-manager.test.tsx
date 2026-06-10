import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TicketTagManager } from "@/components/ticket-tag-manager";
import type { TagRead } from "@/lib/domain/tag";

// Server Action と router を mock し、各操作が正しい action / FormData を呼ぶことを検証する。
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh })
}));

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
  refresh.mockClear();
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
    // C-5 workaround: refresh は transition 内即時呼びでなく useDeferredRouterRefresh の
    // effect 経由 (transition 外) に変更されたため、非同期到達を待つ。
    await waitFor(() => expect(refresh).toHaveBeenCalled());
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
