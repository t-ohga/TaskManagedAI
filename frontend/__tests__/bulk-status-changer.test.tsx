// C-5 workaround の回帰 test (Codex adversarial R1 検証):
// BulkStatusChanger の deferred refresh (useDeferredRouterRefresh) が、全件成功 → onClear() で
// 親の selectedIds が空になっても失われないことを実証する。親は `bulkEnabled` (project view 固定、
// selectedIds 非依存) で条件 render するため、clear 後も component は mount されたまま
// `return null` になるだけ — tick state と effect は生存し、router.refresh() は確実に発火する。
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { BulkStatusChanger } from "@/components/bulk-status-changer";

// C-5 第 2 round: hook は full reload (lib/full-reload seam) を行う。jsdom の location を
// 再定義せず、seam module を mock して検証する (Codex adversarial F-3)。
const reload = vi.fn(() => true);
const discardConfirm = vi.fn(() => true);
const commitDiscard = vi.fn();
vi.mock("@/lib/full-reload", () => ({
  fullReload: () => reload(),
  hasUnsavedDraft: () => false,
  confirmDiscardUnsavedDrafts: () => discardConfirm(),
  // R11: pre-commit は確認のみ、破棄は成功時 commit。bulk は確認結果を approved に反映。
  prepareDiscardOnCommit: () => ({ approved: discardConfirm(), commit: commitDiscard })
}));

const updateCalls: Record<string, string>[] = [];
// id ごとに結果を制御 (F-2 部分失敗 test 用)。default は全件成功。
const failingIds = new Set<string>();
vi.mock("@/app/(admin)/tickets/[id]/actions", () => ({
  updateTicketAction: async (_state: unknown, fd: FormData) => {
    const entries: Record<string, string> = {};
    for (const [k, v] of fd.entries()) entries[k] = String(v);
    updateCalls.push(entries);
    if (failingIds.has(entries.ticket_id ?? "")) {
      return { kind: "error" as const, message: "boom", last_ok_ticket: null };
    }
    return { kind: "ok" as const };
  }
}));

vi.mock("@/components/toast", () => ({
  useToast: () => ({ toast: vi.fn() })
}));

// 親の selectedIds 管理を再現: onClear で空にするが、BulkStatusChanger 自体は
// mount したまま (selectable-ticket-list の bulkEnabled は selectedIds 非依存)。
function Harness({ ids = ["00000000-0000-4000-8000-00000000c001"] }: { ids?: string[] }) {
  const [selectedIds, setSelectedIds] = useState(ids);
  return (
    <BulkStatusChanger
      selectedIds={selectedIds}
      onClear={() => setSelectedIds([])}
      onSelectionChange={setSelectedIds}
    />
  );
}

beforeEach(() => {
  reload.mockClear();
  discardConfirm.mockClear();
  discardConfirm.mockReturnValue(true);
  updateCalls.length = 0;
  failingIds.clear();
});

describe("BulkStatusChanger (C-5 deferred refresh)", () => {
  it("全件成功 → onClear で selectedIds が空になっても deferred reload が発火する", async () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "closed" } });
    fireEvent.click(screen.getByRole("button", { name: /適用|変更|更新/ }));

    await waitFor(() => expect(updateCalls).toHaveLength(1));
    expect(updateCalls[0]).toMatchObject({ status: "closed" });
    // clear 後 (component は return null) でも effect 経由の reload が到達する。
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it("部分失敗時は reload せず、エラー表示と失敗 ID の再選択 (復旧導線) を残す (F-2)", async () => {
    const okId = "00000000-0000-4000-8000-00000000c001";
    const ngId = "00000000-0000-4000-8000-00000000c002";
    failingIds.add(ngId);
    render(<Harness ids={[okId, ngId]} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "closed" } });
    fireEvent.click(screen.getByRole("button", { name: /適用|変更|更新/ }));

    await waitFor(() => expect(updateCalls).toHaveLength(2));
    await screen.findByText(/1 件の更新に失敗/);
    // 失敗があるときは画面を消さない (reload は全件成功時のみ)。
    await new Promise((r) => setTimeout(r, 50));
    expect(reload).not.toHaveBeenCalled();
  });

  it("未保存編集の破棄を拒否したら server action 自体を実行しない (R2 pre-commit gate)", async () => {
    discardConfirm.mockReturnValue(false);
    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "closed" } });
    fireEvent.click(screen.getByRole("button", { name: /適用|変更|更新/ }));

    await new Promise((r) => setTimeout(r, 50));
    // キャンセル時は DB も画面も一切変えない (post-commit 確認だと stale form 保存で
    // commit 済み status を巻き戻せるため、gate は mutation 前)。
    expect(updateCalls).toHaveLength(0);
    expect(reload).not.toHaveBeenCalled();
  });

  it("同 tick の二重 click は inFlightRef で 1 回だけ実行する (R6 同期 lock)", async () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "closed" } });
    const button = screen.getByRole("button", { name: /適用|変更|更新/ });

    // 単一 act 内で 2 連続 dispatch することで、1 回目の startTransition で isPending=true に
    // なっても **再 render (disabled 反映) が flush される前** に 2 回目の click を発火させる。
    // isPending / disabled は次 render まで遅延するため、これが React 19 の sub-tick race を再現する。
    // inFlightRef が無いと startTransition が二重起動し updateTicketAction が 2 回走る (二重 mutation)。
    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    await waitFor(() => expect(reload).toHaveBeenCalled());
    // 二重 click でも updateTicketAction は 1 回だけ (同期 lock が 2 回目を弾く)。
    expect(updateCalls).toHaveLength(1);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("部分失敗時は lock を解放し再試行を許す (R6 失敗時 reset)", async () => {
    const ngId = "00000000-0000-4000-8000-00000000c002";
    failingIds.add(ngId);
    render(<Harness ids={[ngId]} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "closed" } });
    const button = screen.getByRole("button", { name: /適用|変更|更新/ });

    fireEvent.click(button);
    await screen.findByText(/1 件の更新に失敗/);
    expect(updateCalls).toHaveLength(1);

    // 失敗後は lock 解放済み → 再 click で再試行できる (lock が居残ると永久に再実行不能)。
    failingIds.clear();
    fireEvent.click(button);
    await waitFor(() => expect(updateCalls).toHaveLength(2));
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it("全件成功後も lock を解放し、bar が残れば再実行できる (R7 成功時 reset)", async () => {
    // reload (full reload) が別 draft 確認でキャンセルされ bar が mount のまま残る状況を、
    // onClear を no-op にして再現する (実際は selectedIds 空 → null だが、reload 拒否後に
    // 再選択されると bar が再表示される。その時 lock が居残ると dead button になる)。
    const id = "00000000-0000-4000-8000-00000000c001";
    render(
      <BulkStatusChanger selectedIds={[id]} onClear={vi.fn()} onSelectionChange={vi.fn()} />
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "closed" } });
    const button = screen.getByRole("button", { name: /適用|変更|更新/ });

    fireEvent.click(button);
    await waitFor(() => expect(updateCalls).toHaveLength(1));
    await waitFor(() => expect(reload).toHaveBeenCalled());

    // 成功後も lock は解放されているので、bar が残っていれば次の操作を実行できる。
    fireEvent.click(button);
    await waitFor(() => expect(updateCalls).toHaveLength(2));
  });
});
