// R3 (Codex adversarial HIGH/MEDIUM) 回帰 test:
// - 実 EditTicketForm + MarkdownEditor で **description のみ**を編集しても dirty が検知される
//   (DOM value/defaultValue 比較では controlled な説明欄がすり抜けるため data-dirty 方式)。
// - TicketDeleteButton (中止) は破棄確認を拒否したら server action も遷移も実行しない。
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditTicketForm } from "../app/(admin)/tickets/[id]/_components/edit-ticket-form";
import { TicketDeleteButton } from "@/components/ticket-delete-button";
import { hasUnsavedTicketEdit } from "@/lib/full-reload";

const routerMocks = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => routerMocks
}));

const updateCalls: unknown[] = [];
vi.mock("../app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async (_s: unknown, fd: FormData) => {
    updateCalls.push(fd);
    return { kind: "ok" as const, ticket_id: "x", ticket: null };
  }
}));
// delete button は alias import (@/app/...) 経由 — 同 module を alias でも mock する。
vi.mock("@/app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async (_s: unknown, fd: FormData) => {
    updateCalls.push(fd);
    return { kind: "ok" as const, ticket_id: "x", ticket: null };
  }
}));

const toast = vi.fn();
vi.mock("@/components/toast", () => ({ useToast: () => ({ toast }) }));

// jsdom は <dialog> の showModal/close 未実装のため stub する (ConfirmDialog 用)。
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  });
});

// gate は実物 (lib/full-reload) を使う — confirm を spy する。
beforeEach(() => {
  updateCalls.length = 0;
  routerMocks.push.mockClear();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

const TICKET = {
  id: "00000000-0000-4000-8000-00000000f001",
  title: "t",
  description: "initial description",
  due_date: null,
  status: "open",
  priority: null,
  assignee_actor_id: null,
  updated_at: "2026-06-10T00:00:00Z"
};

describe("EditTicketForm dirty 検知 (R3: 実 form + MarkdownEditor)", () => {
  it("description のみの編集でも data-dirty 経由で dirty と判定される", () => {
    render(
      <EditTicketForm
        ticket={TICKET}
        assignableActors={[]}
        assignableActorsDegraded={false}
        assignableActorsTruncated={false}
      />
    );
    expect(hasUnsavedTicketEdit()).toBe(false);
    fireEvent.change(screen.getByLabelText("説明"), {
      target: { value: "edited description" }
    });
    expect(hasUnsavedTicketEdit()).toBe(true);
  });

  it("status select の編集も dirty と判定される", () => {
    render(
      <EditTicketForm
        ticket={TICKET}
        assignableActors={[]}
        assignableActorsDegraded={false}
        assignableActorsTruncated={false}
      />
    );
    fireEvent.change(screen.getByRole("combobox", { name: "状態" }), {
      target: { value: "in_progress" }
    });
    expect(hasUnsavedTicketEdit()).toBe(true);
  });
});

describe("TicketDeleteButton (R3 F-2: pre-commit gate)", () => {
  it("未保存編集の破棄を拒否したら action も遷移も実行しない", async () => {
    render(
      <>
        <EditTicketForm
          ticket={TICKET}
          assignableActors={[]}
          assignableActorsDegraded={false}
          assignableActorsTruncated={false}
        />
        <TicketDeleteButton ticketId={TICKET.id} projectId="p" />
      </>
    );
    fireEvent.change(screen.getByLabelText("説明"), { target: { value: "draft" } });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    fireEvent.click(screen.getByRole("button", { name: "チケットを中止" }));
    // ConfirmDialog を開いて中止を確定する
    const confirmBtn = await screen.findByRole("button", { name: "中止する" });
    fireEvent.click(confirmBtn);

    await new Promise((r) => setTimeout(r, 50));
    expect(updateCalls).toHaveLength(0);
    expect(routerMocks.push).not.toHaveBeenCalled();
  });

  it("dirty なしなら gate は介入せず action + 遷移する", async () => {
    render(<TicketDeleteButton ticketId={TICKET.id} projectId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "チケットを中止" }));
    const confirmBtn = await screen.findByRole("button", { name: "中止する" });
    fireEvent.click(confirmBtn);
    await waitFor(() => expect(updateCalls).toHaveLength(1));
    await waitFor(() => expect(routerMocks.push).toHaveBeenCalledWith("/tickets"));
  });
});
