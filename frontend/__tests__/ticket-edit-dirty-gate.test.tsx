// R3 (Codex adversarial HIGH/MEDIUM) 回帰 test:
// - 実 EditTicketForm + MarkdownEditor で **description のみ**を編集しても dirty が検知される
//   (DOM value/defaultValue 比較では controlled な説明欄がすり抜けるため data-dirty 方式)。
// - TicketDeleteButton (中止) は破棄確認を拒否したら server action も遷移も実行しない。
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditTicketForm } from "../app/(admin)/tickets/[id]/_components/edit-ticket-form";
import { TicketDeleteButton } from "@/components/ticket-delete-button";
import { hasUnsavedDraft } from "@/lib/full-reload";

const routerMocks = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => routerMocks
}));

// R14: action 実行中の副作用 (= ユーザーが mutation 中に draft を編集する状況) を test から注入する。
// vi.hoisted で mock factory より先に初期化される共有 state を確保する。
const shared = vi.hoisted(() => ({
  updateCalls: [] as unknown[],
  actionSideEffect: undefined as undefined | (() => void)
}));
const updateCalls = shared.updateCalls;
// factory は hoist されるため shared (hoisted) のみ参照する literal を直接渡す。
vi.mock("../app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async (_s: unknown, fd: FormData) => {
    shared.updateCalls.push(fd);
    shared.actionSideEffect?.();
    return { kind: "ok" as const, ticket_id: "x", ticket: null };
  }
}));
// delete button は alias import (@/app/...) 経由 — 同 module を alias でも mock する。
vi.mock("@/app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async (_s: unknown, fd: FormData) => {
    shared.updateCalls.push(fd);
    shared.actionSideEffect?.();
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
    expect(hasUnsavedDraft()).toBe(false);
    fireEvent.change(screen.getByLabelText("説明"), {
      target: { value: "edited description" }
    });
    expect(hasUnsavedDraft()).toBe(true);
  });

  it("MarkdownEditor の toolbar 操作 (太字) でも dirty と判定される (R4: guard 直書き)", async () => {
    render(
      <EditTicketForm
        ticket={TICKET}
        assignableActors={[]}
        assignableActorsDegraded={false}
        assignableActorsTruncated={false}
      />
    );
    expect(hasUnsavedDraft()).toBe(false);
    // toolbar の太字ボタンは native input event を発火しないため、MarkdownEditor が祖先の
    // guard 領域へ同期的に data-dirty を直書きする。
    fireEvent.click(screen.getByRole("button", { name: /太字/ }));
    expect(hasUnsavedDraft()).toBe(true);
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
    expect(hasUnsavedDraft()).toBe(true);
  });
});

describe("EditTicketForm 保存と他領域 draft (R5)", () => {
  it("他 guard 領域が dirty なら保存前に確認し、拒否時は action を実行しない", async () => {
    render(
      <EditTicketForm
        ticket={TICKET}
        assignableActors={[]}
        assignableActorsDegraded={false}
        assignableActorsTruncated={false}
      />
    );
    // 別領域 (例: コメント form) の draft を模擬
    const other = document.createElement("div");
    other.setAttribute("data-unsaved-guard", "");
    other.dataset.dirty = "true";
    document.body.appendChild(other);

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.submit(screen.getByTestId("edit-ticket-form"));

    await new Promise((r) => setTimeout(r, 50));
    expect(confirmSpy).toHaveBeenCalled();
    expect(updateCalls).toHaveLength(0);
  });

  it("自 form の dirty だけなら確認なしで保存できる (except=自 form)", async () => {
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
    const confirmSpy = vi.spyOn(window, "confirm");
    fireEvent.submit(screen.getByTestId("edit-ticket-form"));
    await waitFor(() => expect(updateCalls).toHaveLength(1));
    expect(confirmSpy).not.toHaveBeenCalled();
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

  it("R14: 承認後に draft を編集 (in-flight) → commit skip → 遷移前再確認を拒否で router.push しない", async () => {
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
    const description = screen.getByLabelText("説明") as HTMLTextAreaElement;
    fireEvent.change(description, { target: { value: "approved draft" } });

    // action 実行中 (= 中止 mutation in-flight) に同じ draft を編集 → signature 変化で commit が skip。
    shared.actionSideEffect = () => {
      fireEvent.change(description, { target: { value: "edited after approval" } });
    };
    // pre-commit 承認 (true) → 遷移前 R7 再確認は拒否 (false)。
    vi.spyOn(window, "confirm").mockReturnValueOnce(true).mockReturnValue(false);

    fireEvent.click(screen.getByRole("button", { name: "チケットを中止" }));
    fireEvent.click(await screen.findByRole("button", { name: "中止する" }));

    await waitFor(() => expect(updateCalls).toHaveLength(1)); // 中止 mutation は成功
    await new Promise((r) => setTimeout(r, 50));
    // post-approval 編集が commit で skip され dirty 残存 → 遷移前再確認で拒否 → 遷移せず draft 保持
    expect(routerMocks.push).not.toHaveBeenCalled();
    expect(description.value).toBe("edited after approval");
    shared.actionSideEffect = undefined;
  });
});
