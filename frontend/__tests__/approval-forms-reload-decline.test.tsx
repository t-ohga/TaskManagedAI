// R7 (Codex adversarial HIGH) 回帰 test:
// 判定 / 修正依頼が DB 上は成功したのに、reload 直前の破棄確認 (mutation 中に作られた別 draft 由来)
// をユーザーが拒否して full reload が起きなかった場合でも、form が「見た目有効・実際 inFlightRef で
// 無言ブロックされる dead button」にならないことを固定する。成功後は decided/requested で fieldset を
// 可視的に無効化する設計のため、reload 有無に依存せず操作子は disabled になる。
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as FullReloadModule from "@/lib/full-reload";

import { ApprovalDecideForm } from "../app/(admin)/approvals/[id]/_components/approval-decide-form";
import { ApprovalRevisionRequestForm } from "../app/(admin)/approvals/[id]/_components/approval-revision-request-form";
import { ApprovalPendingActions } from "../app/(admin)/approvals/[id]/_components/approval-pending-actions";

// reload seam を mock。confirmDiscardUnsavedDrafts は test ごとに返り値を制御し、
// 「reload 直前の破棄確認をユーザーが拒否 → fullReload 呼ばれない」状況を再現する。
// DRAFT_DISCARD_EVENT 等の他 export は real を保つ (use-draft-discard が依存)。
const fullReloadSpy = vi.fn();
let reloadConfirmReturn = true;
vi.mock("@/lib/full-reload", async (importOriginal) => {
  const actual = await importOriginal<typeof FullReloadModule>();
  return {
    ...actual,
    fullReload: () => fullReloadSpy(),
    // reload 直前の再確認 (useDeferredRouterRefresh の effect 内)。
    confirmDiscardUnsavedDrafts: () => reloadConfirmReturn,
    // submit 時の pre-commit gate (今回は常に approve、破棄は即 commit)。
    prepareDiscardOnCommit: () => ({ approved: true, commit: vi.fn() })
  };
});

const decideSpy = vi.fn();
vi.mock("@/app/(admin)/approvals/[id]/_actions/decide", () => ({
  decideApprovalAction: (...args: unknown[]) => decideSpy(...args)
}));

const revisionSpy = vi.fn();
vi.mock("@/app/(admin)/approvals/[id]/_actions/request-revision", () => ({
  requestApprovalRevisionAction: (...args: unknown[]) => revisionSpy(...args)
}));

beforeEach(() => {
  fullReloadSpy.mockClear();
  reloadConfirmReturn = true;
  decideSpy.mockReset();
  revisionSpy.mockReset();
});

describe("ApprovalDecideForm — reload 拒否後の terminal lock (R7)", () => {
  it("判定成功後に reload が拒否されても、ボタンは disabled になり dead button にならない", async () => {
    decideSpy.mockResolvedValue({ ok: true, status: "approved" });
    reloadConfirmReturn = false; // mutation 中に別 draft が作られ、reload 直前確認を拒否した状況

    render(
      <ApprovalDecideForm
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    const approveButton = screen.getByRole("button", { name: "承認" });
    expect(approveButton).toBeEnabled();

    fireEvent.click(approveButton);

    await waitFor(() => expect(decideSpy).toHaveBeenCalledTimes(1));
    await screen.findByText(/判定を保存しました/);

    // reload は拒否されたので full reload は起きない (別 draft 保持を優先)。
    expect(fullReloadSpy).not.toHaveBeenCalled();
    // それでも判定済み form は可視的に無効化され、再 submit を無言で握り潰す dead button にならない。
    await waitFor(() => expect(screen.getByRole("button", { name: "承認" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "却下" })).toBeDisabled();
  });

  it("判定成功後に reload が実行される通常経路では fullReload が発火する", async () => {
    decideSpy.mockResolvedValue({ ok: true, status: "approved" });
    reloadConfirmReturn = true;

    render(
      <ApprovalDecideForm
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "承認" }));

    await waitFor(() => expect(decideSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(fullReloadSpy).toHaveBeenCalledTimes(1));
  });

  it("判定失敗時は lock を解放し、ボタンは有効なまま再試行できる", async () => {
    decideSpy.mockResolvedValue({ ok: false, error: "判定に失敗しました" });

    render(
      <ApprovalDecideForm
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "承認" }));

    await waitFor(() => expect(decideSpy).toHaveBeenCalledTimes(1));
    await screen.findByText("判定に失敗しました");
    // 失敗は terminal ではない。decided にならず、ボタンは有効なまま再試行できる。
    await waitFor(() => expect(screen.getByRole("button", { name: "承認" })).toBeEnabled());

    decideSpy.mockResolvedValue({ ok: true, status: "approved" });
    fireEvent.click(screen.getByRole("button", { name: "承認" }));
    await waitFor(() => expect(decideSpy).toHaveBeenCalledTimes(2));
  });
});

describe("ApprovalRevisionRequestForm — reload 拒否後の terminal lock (R7)", () => {
  it("修正依頼成功後に reload が拒否されても、ボタンは disabled になり dead button にならない", async () => {
    revisionSpy.mockResolvedValue({ ok: true, status: "pending" });
    reloadConfirmReturn = false;

    render(
      <ApprovalRevisionRequestForm
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    fireEvent.change(screen.getByLabelText("修正理由"), {
      target: { value: "再提出前に直す内容" }
    });
    const submitButton = screen.getByRole("button", { name: "修正依頼" });
    expect(submitButton).toBeEnabled();

    fireEvent.click(submitButton);

    await waitFor(() => expect(revisionSpy).toHaveBeenCalledTimes(1));
    await screen.findByText(/修正依頼を保存しました/);

    expect(fullReloadSpy).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "修正依頼" })).toBeDisabled()
    );
  });

  it("修正依頼失敗時は lock を解放し、ボタンは有効なまま再試行できる", async () => {
    revisionSpy.mockResolvedValue({ ok: false, error: "修正依頼に失敗しました" });

    render(
      <ApprovalRevisionRequestForm
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    fireEvent.change(screen.getByLabelText("修正理由"), {
      target: { value: "再提出前に直す内容" }
    });
    fireEvent.click(screen.getByRole("button", { name: "修正依頼" }));

    await waitFor(() => expect(revisionSpy).toHaveBeenCalledTimes(1));
    await screen.findByText("修正依頼に失敗しました");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "修正依頼" })).toBeEnabled()
    );
  });
});

describe("ApprovalPendingActions — sibling form 協調 (Codex auto-review P2)", () => {
  it("判定 form の成功で sibling の修正依頼 form も無効化される", async () => {
    decideSpy.mockResolvedValue({ ok: true, status: "approved" });
    // reload を拒否させ、両 form が unmount されず mount のまま残る状況で sibling 無効化を検証。
    reloadConfirmReturn = false;

    render(
      <ApprovalPendingActions
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    const approveButton = screen.getByRole("button", { name: "承認" });
    const revisionButton = screen.getByRole("button", { name: "修正依頼" });
    expect(approveButton).toBeEnabled();
    expect(revisionButton).toBeEnabled();

    fireEvent.click(approveButton);
    await waitFor(() => expect(decideSpy).toHaveBeenCalledTimes(1));

    // 判定成功で判定 form (decided) と修正依頼 form (siblingTerminal) の両方が無効化される。
    await waitFor(() => expect(screen.getByRole("button", { name: "承認" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "却下" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "修正依頼" })).toBeDisabled();
    // sibling の action は一度も呼ばれない (stale な二重 terminal action を防ぐ)。
    expect(revisionSpy).not.toHaveBeenCalled();
  });

  it("修正依頼 form の成功で sibling の判定 form も無効化される", async () => {
    revisionSpy.mockResolvedValue({ ok: true, status: "pending" });
    reloadConfirmReturn = false;

    render(
      <ApprovalPendingActions
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    fireEvent.change(screen.getByLabelText("修正理由"), {
      target: { value: "再提出前に直す内容" }
    });
    fireEvent.click(screen.getByRole("button", { name: "修正依頼" }));
    await waitFor(() => expect(revisionSpy).toHaveBeenCalledTimes(1));

    await waitFor(() => expect(screen.getByRole("button", { name: "修正依頼" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "承認" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "却下" })).toBeDisabled();
    expect(decideSpy).not.toHaveBeenCalled();
  });
});
